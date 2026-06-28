from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
from fastapi.staticfiles import StaticFiles
from langchain_google_genai import ChatGoogleGenerativeAI
import json
import re
import os
import secrets
from typing import Any, Optional
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
app = FastAPI(title="Kapruka AI Assistant")
app.mount("/static", StaticFiles(directory="."), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.1,
)

ORDER_LOG_FILE = "order_log.txt"

# ========== AUTHENTICATION ==========
# Simple in-memory user store (replace with database in production)
USERS = {
    "admin": "1234",
    "kapruka": "kapruka2024",
}

# Store active sessions (in production, use Redis or database)
active_sessions = {}

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    message: str
    order: dict[str, Any] | None = None

def verify_token(token: str) -> bool:
    """Verify if a session token is valid."""
    return token in active_sessions

def get_current_user(token: str = "") -> Optional[str]:
    """Get current username from token."""
    if token in active_sessions:
        return active_sessions[token]
    return None

@app.post("/login")
async def login(req: LoginRequest):
    """Authenticate user and return session token."""
    username = os.getenv("ADMIN_USER")
    password = os.getenv("ADMIN_PASSWORD")
    
    if username not in USERS or USERS[username] != password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Generate secure session token
    token = secrets.token_urlsafe(32)
    active_sessions[token] = username
    
    return {
        "success": True,
        "token": token,
        "username": username,
        "message": f"Welcome, {username}!"
    }

@app.post("/logout")
async def logout(token: str):
    """Logout user and invalidate token."""
    if token in active_sessions:
        del active_sessions[token]
    return {"success": True, "message": "Logged out successfully"}

@app.get("/verify")
async def verify_session(token: str):
    """Verify if a session token is still valid."""
    if verify_token(token):
        return {
            "valid": True,
            "username": active_sessions[token]
        }
    return {"valid": False}

# ========== EXISTING CHAT LOGIC ==========

def tool_result_to_text(result) -> str:
    if hasattr(result, "structuredContent") and result.structuredContent:
        return result.structuredContent.get("result", "")
    if hasattr(result, "content") and result.content:
        return getattr(result.content[0], "text", "")
    return str(result)


def missing_create_order_fields(args: dict) -> list[str]:
    missing = []
    cart = args.get("cart")
    if not isinstance(cart, list) or not cart:
        missing.append("cart item")
    else:
        first_item = cart[0]
        if not isinstance(first_item, dict) or not first_item.get("product_id"):
            missing.append("product ID")

    recipient = args.get("recipient") if isinstance(args.get("recipient"), dict) else {}
    if not recipient.get("name"):
        missing.append("recipient name")
    if not recipient.get("phone"):
        missing.append("recipient phone")

    delivery = args.get("delivery") if isinstance(args.get("delivery"), dict) else {}
    if not delivery.get("address"):
        missing.append("delivery address")
    if not delivery.get("city"):
        missing.append("delivery city")
    if not delivery.get("date"):
        missing.append("delivery date")

    sender = args.get("sender") if isinstance(args.get("sender"), dict) else {}
    if not sender.get("name"):
        missing.append("sender name")

    return missing


def missing_order_message(missing: list[str]) -> str:
    return "To create this order I still need: " + ", ".join(missing) + "."


def extract_order_number(text: str) -> str | None:
    match = re.search(r"ORD-[A-Z0-9-]+", text, re.IGNORECASE)
    if match:
        return match.group(0)
    match = re.search(r"KP[A-Z0-9-]+", text, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


def extract_first_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip(").,]") if match else None


def save_order_log(order: dict, result_text: str) -> None:
    cart = order.get("cart") if isinstance(order.get("cart"), list) else []
    print("EXTRACTED ORDER:", extract_order_number(result_text))
    record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "cart": cart,
        "recipient": order.get("recipient", {}),
        "delivery": order.get("delivery", {}),
        "sender": order.get("sender", {}),
        "order_number": extract_order_number(result_text),
        "checkout_url": extract_first_url(result_text),
        "result": result_text[:2000],
    }
    with open(ORDER_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_order_log(limit: int = 10) -> list[dict]:
    if not os.path.exists(ORDER_LOG_FILE):
        return []
    records = []
    with open(ORDER_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return list(reversed(records[-limit:]))


def format_saved_orders(records: list[dict]):
    if not records:
        return "I do not have any saved orders yet. Create an order first, then I can help track it."
    lines = ["Which saved product/order do you want to track? Reply with the product ID or order number."]
    for index, record in enumerate(records, start=1):
        cart = record.get("cart") or []
        product_ids = ", ".join(
            item.get("product_id", "unknown") for item in cart if isinstance(item, dict)
        ) or "unknown product"
        order_number = record.get("order_number") or "order number not saved yet"
        created_at = record.get("created_at", "unknown time")
        lines.append(f"{index}. Product ID: {product_ids} | Order: {order_number} | Saved: {created_at}")
    return "\n".join(lines)


def saved_orders_for_ui(records: list[dict]) -> list[dict]:
    orders = []
    for index, record in enumerate(records, start=1):
        cart = record.get("cart") or []
        product_ids = [
            str(item.get("product_id", "unknown"))
            for item in cart
            if isinstance(item, dict)
        ]
        order_number = record.get("order_number") or ""
        track_token = order_number or (product_ids[0] if product_ids else "")
        orders.append({
            "index": index,
            "product_ids": product_ids,
            "order_number": order_number,
            "created_at": record.get("created_at", ""),
            "recipient_name": (record.get("recipient") or {}).get("name", ""),
            "delivery_city": (record.get("delivery") or {}).get("city", ""),
            "checkout_url": record.get("checkout_url") or "",
            "track_token": track_token,
            "can_track": bool(track_token),
        })
    return orders


def should_show_saved_orders(query: str) -> bool:
    lower = query.lower()
    keywords = [
        "track my order", "show my order", "show me my order", "my order",
        "my orders", "order history", "what did i order", "show orders",
        "show order", "orders", "where is my order"
    ]
    return any(k in lower for k in keywords)


def find_saved_order_by_token(query: str) -> dict | None:
    token = query.strip().upper()
    if not token or " " in token:
        return None
    for record in load_order_log(limit=50):
        order_number = (record.get("order_number") or "").upper()
        if order_number and token == order_number:
            return record
        for item in record.get("cart") or []:
            if isinstance(item, dict) and token == str(item.get("product_id", "")).upper():
                return record
    return None


async def call_selected_tool(name: str, args: dict):
    try:
        print("================================")
        print("CALLING MCP TOOL")
        print("Tool Name:", name)
        print("Arguments:", args)
        print("================================")

        async with streamablehttp_client("https://mcp.kapruka.com/mcp") as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                mcp_arguments = {"params": args}
                result = await session.call_tool(name, mcp_arguments)
                print("MCP RESPONSE:")
                return result
    except Exception as e:
        error_text = str(e)
        print("Tool call error:", error_text)
        if "recipient.phone" in error_text:
            return {"friendly_error": "Please enter a valid phone number (minimum 7 digits)."}
        if "delivery.address" in error_text:
            return {"friendly_error": "Please enter a valid delivery address."}
        if "delivery.date" in error_text:
            return {"friendly_error": "Please enter the delivery date in YYYY-MM-DD format."}
        return {"friendly_error": "Unable to create the order. Please verify the details and try again."}


@app.get("/")
async def root():
    return FileResponse("website - Copy.html")


@app.get("/tools")
async def tools():
    async with streamablehttp_client("https://mcp.kapruka.com/mcp") as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            for tool in tools.tools:
                if tool.name == "kapruka_create_order":
                    return {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema
                    }
            return {"error": "not found"}


@app.post("/chat")
async def chat(req: ChatRequest):
    user_query = req.message.strip()
    with open("chat_log.txt", "a", encoding="utf-8") as f:
        f.write(f"User: {user_query}\n")

    if req.order:
        missing = missing_create_order_fields(req.order)
        if missing:
            return {
                "type": "result",
                "tool": "kapruka_create_order",
                "result": missing_order_message(missing),
                "checkout_url": extract_first_url(""),
                "order_number": extract_order_number("")
            }

        result = await call_selected_tool("kapruka_create_order", req.order)

        if not result:
            return {"type": "result", "result": "Order creation failed."}

        result_text = tool_result_to_text(result)
        checkout_url = extract_first_url(result_text)
        order_number = extract_order_number(result_text)

        if not getattr(result, "isError", False):
            save_order_log(req.order, result_text)

        return {
            "type": "result",
            "tool": "kapruka_create_order",
            "result": result_text,
            "checkout_url": checkout_url,
            "order_number": order_number
        }

    if should_show_saved_orders(user_query):
        saved_orders = load_order_log()
        return {
            "type": "saved_orders",
            "tool": "saved_orders",
            "result": format_saved_orders(saved_orders),
            "orders": saved_orders_for_ui(saved_orders)
        }

    saved_order = find_saved_order_by_token(user_query)
    if saved_order:
        order_number = saved_order.get("order_number")
        if order_number:
            result = await call_selected_tool("kapruka_track_order", {"order_number": order_number})
            return {
                "type": "result",
                "tool": "kapruka_track_order",
                "result": tool_result_to_text(result) if result else "Could not track that saved order."
            }
        product_ids = ", ".join(
            item.get("product_id", "unknown")
            for item in saved_order.get("cart") or []
            if isinstance(item, dict)
        )
        return {
            "type": "result",
            "tool": "saved_orders",
            "result": "I found saved product " + product_ids + ", but no order number was saved from the checkout result. Please use the order number from the payment/checkout page."
        }

    if user_query.lower().startswith("buy product "):
        product_id = user_query[12:].strip()
        if product_id:
            return {
                "type": "result",
                "tool": "kapruka_create_order",
                "result": (
                    "To create this order I need recipient name, recipient phone, "
                    "delivery address, city, delivery date, and sender name."
                )
            }

    tool_prompt = f"""
User request: {user_query}

You are a Kapruka Shopping Assistant.

Language Rules:
* If the user writes in Sinhala, reply in Sinhala.
* If the user writes in English, reply in English.
* If the user mixes Sinhala and English, reply mainly in Sinhala.
* Keep responses short and helpful.
* Never translate Product IDs or Order Numbers.
* Product names may remain in English.
* When asking for missing information, ask in the same language as the user.

Your job is to understand the user's shopping intent and select the best MCP tool.

Available Tools:
kapruka_search_products
{{
"q":"search keywords",
"category":"",
"min_price":0,
"max_price":0,
"in_stock_only":true,
"sort":"",
"limit":20
}}

kapruka_get_product
{{
"product_id":"product id"
}}

kapruka_list_categories
{{
"depth":1
}}

kapruka_list_delivery_cities
{{
"query":"city name",
"limit":20
}}

kapruka_check_delivery
{{
"city":"city name",
"product_id":"product id"
}}

kapruka_track_order
{{
"order_number":"order number"
}}

kapruka_create_order
{{
"cart":[{{"product_id":"product id","quantity":1}}],
"recipient":{{"name":"recipient name","phone":"recipient phone"}},
"delivery":{{"address":"street address","city":"delivery city","date":"YYYY-MM-DD"}},
"sender":{{"name":"sender name","anonymous":false}},
"gift_message":null,
"currency":"LKR"
}}

Rules:
1. Product search → kapruka_search_products
2. Product details → kapruka_get_product
3. Delivery availability → kapruka_check_delivery
4. Track order → kapruka_track_order
5. Category browsing → kapruka_list_categories
6. Delivery city search → kapruka_list_delivery_cities
7. Create checkout order → kapruka_create_order

Important:
* Never call kapruka_create_order with missing fields.
* Never call kapruka_create_order with empty cart.
* Never invent recipient information.
* Never invent delivery information.
* Never invent sender information.
* If information is missing, ask the user for it in plain text.
* Do not return JSON when asking for missing information.

Order Tracking:
If the user says: track my order, show my order, show me my order, my orders, order history, where is my order, මගේ ඇණවුම, මගේ ඕඩරය, මගේ ඇණවුම බලන්න → choose order tracking.

Budget Handling:
User: dog toy under 5000 → {{"tool_name":"kapruka_search_products","arguments":{{"q":"dog toy","max_price":5000,"in_stock_only":true,"limit":20}}}}
User: saree under 10000 → {{"tool_name":"kapruka_search_products","arguments":{{"q":"saree","max_price":10000,"in_stock_only":true,"limit":20}}}}
User: product KIDSTOY0Z1366 → {{"tool_name":"kapruka_get_product","arguments":{{"product_id":"KIDSTOY0Z1366"}}}}
User: can you deliver KIDSTOY0Z1366 to Colombo → {{"tool_name":"kapruka_check_delivery","arguments":{{"city":"Colombo","product_id":"KIDSTOY0Z1366"}}}}
User: track order KP123456 → {{"tool_name":"kapruka_track_order","arguments":{{"order_number":"KP123456"}}}}
User: මට රුපියල් 5000 ට අඩු සෙල්ලම් බඩුවක් ඕන → {{"tool_name":"kapruka_search_products","arguments":{{"q":"toy","max_price":5000,"in_stock_only":true,"limit":20}}}}

Return ONLY JSON when selecting a tool.
Required format: {{"tool_name":"tool_name_here","arguments":{{}}}}

Sinhala Conversation Rules:
* Use natural Sri Lankan Sinhala.
* Be polite and friendly.
* Keep product names and Product IDs in English.
* Keep order numbers in English.
* Explain prices in Sinhala.
* Ask missing details in Sinhala.

Examples:
User: මට ලන්ච් එකක් කියන්න → මෙන්න ඔබට සුදුසු ලන්ච් නිර්දේශ කිහිපයක්.
User: මට තෑග්ගක් ඕන → මෙන්න ඔබට ගැලපෙන තෑගි කිහිපයක්.
User: මගේ ඇණවුම බලන්න → කරුණාකර ඔබගේ Order Number එක ලබා දෙන්න.
User: මේක කොළඹට එවන්න පුළුවන්ද? → කරුණාකර නගරයේ නම ලබා දෙන්න.

Also user tell some like eat or recommend of it you have to recommend in both sinhala and english.
Example:
User: මට බඩ ගිනි මොනවා හරි කන්න ඕනේ
Assistant: මොනවාද ඔයා කැමති මට කියන්න
User: මොනවා හරි පැනි රස දෙයක්
"""

    try:
        response = llm.invoke(tool_prompt)
        raw_text = response.content if hasattr(response, "content") else str(response)
        if isinstance(raw_text, list):
            raw_text = "".join(str(x) for x in raw_text)
        print("LLM Raw Response:", raw_text)

        cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()

        if not cleaned.startswith("{"):
            return {"type": "result", "result": cleaned}

        try:
            decision = json.loads(cleaned)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            decision, _ = decoder.raw_decode(cleaned)

        if isinstance(decision, list):
            decision = decision[0] if decision else {}

    except Exception as e:
        print("JSON Parse Error:", e)
        return {
            "type": "result",
            "result": raw_text if "raw_text" in locals() else "Unable to process request"
        }

    tool_name = decision.get("tool_name")
    tool_arguments = decision.get("arguments", {})

    if tool_name == "kapruka_create_order":
        missing = missing_create_order_fields(tool_arguments)
        if missing:
            return {
                "type": "result",
                "tool": "kapruka_create_order",
                "result": missing_order_message(missing)
            }

    if not tool_name:
        return {"type": "result", "result": "No tool selected."}

    result = await call_selected_tool(tool_name, tool_arguments)

    if not result:
        return {
            "result": (
                "I couldn't create the order. Please check the following:\n\n"
                "• Phone number must contain at least 7 digits\n"
                "• Address must contain at least 3 characters\n"
                "• Delivery date must be in YYYY-MM-DD format\n\n"
                "Example:\n"
                "Phone: 0771234567\n"
                "Address: 123 Main Street, Colombo\n"
                "Date: 2026-06-20"
            )
        }

    result_text = tool_result_to_text(result)
    if tool_name == "kapruka_create_order" and not getattr(result, "isError", False):
        save_order_log(tool_arguments, result_text)

    with open("chat_log.txt", "a", encoding="utf-8") as f:
        f.write(f"User: {user_query}\n")
        f.write(f"Tool: {tool_name}\n")
        f.write(f"Result: {result_text}\n")
        f.write("=" * 50 + "\n")

    if tool_name == "kapruka_search_products":
        pattern = r"\*\*(.+?)\*\*\s+ID:\s+`(.+?)`\s+·\s+LKR\s+([\d,]+).*?\[View product\]\((.+?)\)"
        matches = re.findall(pattern, result_text, re.DOTALL | re.IGNORECASE)
        products = []
        for name, pid, price, url in matches:
            products.append({
                "name": name.strip(),
                "id": pid.strip(),
                "price": price.strip(),
                "url": url.strip()
            })
        return {
            "type": "products",
            "products": products,
            "count": len(products)
        }

    return {
        "type": "result",
        "tool": tool_name,
        "result": result_text[:2000],
        "checkout_url": extract_first_url(result_text),
        "order_number": extract_order_number(result_text)
    }
