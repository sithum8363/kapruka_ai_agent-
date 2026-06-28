# Kapruka AI Shopping Assistant

An AI-powered shopping assistant built with FastAPI, Gemini AI, and Kapruka MCP tools.

## Features

* AI-powered shopping assistant
* Product search using Kapruka MCP
* Product details lookup
* Shopping cart system
* Order creation
* Order tracking
* Saved order history
* Voice input support
* Sinhala and English support
* Checkout link generation
* FastAPI backend
* Modern HTML/CSS/JavaScript frontend

---

## Technologies

* Python
* FastAPI
* Gemini 2.5 Flash
* LangChain
* Kapruka MCP
* HTML
* CSS
* JavaScript
* Speech Recognition API

---

## Project Structure

```text
project/
│
├── main.py
├── website.html
├── .env
├── order_log.txt
├── chat_log.txt
├── requirements.txt
└── README.md
```

---

## Installation

### Clone the repository

```bash
git clone https://github.com/sithum8363/kapruka_ai_agent-.git

cd kapruka_ai_agent-
```

### Create virtual environment

```bash
python -m venv venv
```

### Activate virtual environment

Windows:

```bash
venv\Scripts\activate
```

Linux:

```bash
source venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file.

```env
GOOGLE_API_KEY=your_gemini_api_key
MCP_URL=https://mcp.kapruka.com/mcp
ADMIN_USER=admin
ADMIN_PASSWORD=1234
```

---

## Run FastAPI

```bash
uvicorn main:app --reload
```

Server:

```text
http://127.0.0.1:8000
```

---

## Voice Support

The system supports:

* Sinhala voice input
* English voice input
* Microphone status indicator
* Speech-to-text conversion

---

## Supported MCP Tools

* kapruka_search_products
* kapruka_get_product
* kapruka_create_order
* kapruka_track_order
* kapruka_check_delivery
* kapruka_list_categories
* kapruka_list_delivery_cities

---

## Order Flow

1. Search products.
2. Add products to cart.
3. Enter delivery information.
4. Create order.
5. Receive checkout link.
6. Complete payment.
7. Track order using the real order number.

---

## Languages

* English
* Sinhala
* Mixed Sinhala-English conversations

---

## Security

* API keys stored in `.env`
* Sensitive files excluded using `.gitignore`
* Login support available

---

## Author

Sithum

Computer Science with Artificial Intelligence Student

---

## License

This project is provided for educational and research purposes.

```
```
