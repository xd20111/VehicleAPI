# Vehicle Information Lookup API

A Flask-based REST API service to query Indian vehicle registration details via upstream integration, featuring response cleaning, XML/JSON parsing, in-memory caching, and request deduplication.

---

## 🛠️ Prerequisites

- **Python 3.8+** installed on your system.
  - If not installed, download from [python.org](https://www.python.org/downloads/) or install via Microsoft Store.
  - Make sure to check **"Add Python to PATH"** during installation.

---

## 🚀 Setup & Run Instructions

### 1. Open Terminal in Project Directory
Open PowerShell or Command Prompt in this project root folder.

### 2. (Optional but Recommended) Create a Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Run the API Server
```powershell
python Vehicle.py
```
The server will start on: `http://localhost:5000`

---

## 📡 API Endpoints & Usage

### 🔐 API Key Configuration
By default, the API accepts either:
- `Vehicle-key_s0undw4v3` (default project key)
- `your_secret_api_key` (testing key)

You can set custom API keys:
- **Locally**: Set environment variable `API_KEY="your_custom_key"` (or comma-separated `API_KEYS="key1,key2"`).
- **On Vercel**: Add `API_KEY` under **Project Settings &rarr; Environment Variables**.

---

### 1. Health Check & Status
- **URL**: `GET /` or `GET /health` (also `GET /api/health`)
- **Example**:
  ```powershell
  curl http://localhost:5000/
  curl http://localhost:5000/health
  ```

---

### 2. Protected Vehicle Details Lookup
- **URL**: `/vehicle` (or `/api/vehicle`)
- **Methods**: `GET` or `POST` (supports JSON and Form-Encoded)
- **Parameters**:
  - `key` (*required*): Your API key (e.g. `Vehicle-key_s0undw4v3` or `your_secret_api_key`).
  - `query` (*required*): Indian vehicle registration number (e.g. `BR05PB3111`, `MH12AB1234`, `22BH1234AA`). *Aliases `quiry`, `number`, `reg_no` are also supported.*
  - `product_id` (*optional*, default: `1`): Category ID (1 to 12).
  - `cache` (*optional*, default: `yes`): Set to `no` to bypass cache.

#### 🔗 Browser / GET Request Format:
```
http://localhost:5000/vehicle?key=Vehicle-key_s0undw4v3&query=BR05PB3111
```

#### PowerShell / curl Example:
```powershell
curl "http://localhost:5000/vehicle?key=Vehicle-key_s0undw4v3&query=BR05PB3111"
```

#### POST Request Example:
```powershell
curl -X POST http://localhost:5000/vehicle `
  -H "Content-Type: application/json" `
  -d '{"key": "Vehicle-key_s0undw4v3", "query": "BR05PB3111"}'
```

#### Unauthorized Response (if key is missing/wrong):
```json
{
  "status": "error",
  "error": "Unauthorized",
  "message": "Invalid or missing API key. Usage: /vehicle?key={api_key}&query={vehicle_number}"
}
```

---

## ⚡ Deploy to Vercel (Free Hosting)

### Method 1: Using GitHub (Easiest)
1. Push this project folder to a repository on **GitHub**.
2. Go to **[vercel.com](https://vercel.com/)** and sign in.
3. Click **"Add New" -> "Project"**.
4. Select your GitHub repository and click **"Deploy"**.
5. Vercel will automatically build and assign a free live URL (e.g., `https://your-project.vercel.app`).

### Method 2: Using Vercel CLI
1. Open PowerShell in this folder:
   ```powershell
   npx vercel
   ```
2. Follow the login and setup prompts.
3. Deploy to production:
   ```powershell
   npx vercel --prod
   ```

