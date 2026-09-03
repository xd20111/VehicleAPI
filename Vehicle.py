import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

import requests
from flask import Flask, jsonify, request

# API Key Protection Configuration
# Set your API Key via Environment Variable 'API_KEY' or change default below
DEFAULT_API_KEY = os.environ.get("API_KEY", "Vehicle-key_s0undw4v3")
_api_keys_env = os.environ.get("API_KEYS", "")
if _api_keys_env:
    VALID_API_KEYS = {k.strip() for k in _api_keys_env.split(",") if k.strip()}
else:
    # Accept both default key and README documented key for convenience
    VALID_API_KEYS = {DEFAULT_API_KEY, "your_secret_api_key"}

UPSTREAM = os.environ.get("UPSTREAM_URL", "https://horizon.policyboss.com:5443/quote/vehicle_info_loggedin")
SECRET_KEY = os.environ.get("UPSTREAM_SECRET_KEY", "SECRET-HZ07QRWY-JIBT-XRMQ-ZP95-J0RWP3DYRACW")
CLIENT_KEY = os.environ.get("UPSTREAM_CLIENT_KEY", "CLIENT-CNTP6NYE-CU9N-DUZW-CSPI-SH1IS4DOVHB9")
SOURCE = os.environ.get("UPSTREAM_SOURCE", "PB-BETA")
# Tuned for serverless environments (e.g. Vercel 10-15s limit)
UPSTREAM_TIMEOUT = int(os.environ.get("UPSTREAM_TIMEOUT", 10))
CACHE_TTL = int(os.environ.get("CACHE_TTL", 3600))

HEADERS = {
    "Content-Type": "application/json;charset=utf-8",
    "Accept": "application/json",
    "Origin": "https://www.policyboss.com",
    "Referer": "https://www.policyboss.com/car-insurance",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}

# Matches standard Indian state plates (e.g. DL01AB1234, MH12A1) and Bharat (BH) series (e.g. 22BH1234AA)
REGEX = re.compile(
    r"^[A-Z]{2}\s?\d{1,2}\s?[A-Z]{0,3}\s?\d{1,4}$|^\d{2}\s?BH\s?\d{4}\s?[A-Z]{1,2}$", re.I
)
REGEX_STRIP = re.compile(r"[\s-]+")

_local = threading.local()
_cache = {}
_cache_lock = threading.Lock()
_inflight = {}
_inflight_lock = threading.Lock()

_boot = time.time()

app = Flask(__name__)


def _session() -> requests.Session:
    s = getattr(_local, "sess", None)
    if s is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        s.cookies.set("source", SOURCE)
        _local.sess = s
    return s


def normalize_number(number: str) -> str:
    return REGEX_STRIP.sub("", number or "").upper()


def is_valid_number(number: str) -> bool:
    return bool(REGEX.match(number.strip()))


def _cache_get(key: str):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit["ts"] + CACHE_TTL > time.time():
            return hit["data"]
        if hit:
            _cache.pop(key, None)
    return None


def _cache_set(key: str, data):
    with _cache_lock:
        _cache[key] = {"ts": time.time(), "data": data}


def parse_fastlane_response(fastlane_response):
    if not fastlane_response:
        return None
    
    # If already a parsed dictionary or list
    if isinstance(fastlane_response, (dict, list)):
        return fastlane_response
    
    if not isinstance(fastlane_response, str):
        return None
    
    try:
        return json.loads(fastlane_response)
    except (json.JSONDecodeError, TypeError):
        pass
    
    try:
        root = ET.fromstring(fastlane_response)
        
        def element_to_dict(elem):
            result = {}
            if elem.attrib:
                result.update(elem.attrib)
            
            for child in elem:
                child_dict = element_to_dict(child)
                if child.tag in result:
                    if not isinstance(result[child.tag], list):
                        result[child.tag] = [result[child.tag]]
                    result[child.tag].append(child_dict)
                else:
                    result[child.tag] = child_dict
            
            if elem.text and elem.text.strip():
                if len(result) == 0:
                    result = elem.text.strip()
                else:
                    result["text"] = elem.text.strip()
            
            return result
        
        return {root.tag: element_to_dict(root)}
    except (ET.ParseError, TypeError, Exception):
        return None


def clean_upstream(raw: dict) -> dict:
    junk = {"Ip_Address", "Calling_Source", "Product_Id_Request", "Ss_Id", "Channel",
            "Is_LM", "FastLaneId", "Match_Mode", "FastlaneResponse", "FastlaneResponse_Obj"}
    no_vahan = raw.get("0") == "N" or all(k.isdigit() for k in list(raw)[:6])
    out = {k: v for k, v in raw.items() if k not in junk and not k.isdigit()}
    
    if "FastlaneResponse" in raw and raw["FastlaneResponse"]:
        parsed = parse_fastlane_response(raw["FastlaneResponse"])
        if parsed:
            out["vehicle_details"] = parsed
            
    has_details = bool(
        out.get("Make_Name")
        or out.get("Maker_Name")
        or out.get("Model_Name")
        or out.get("Vehicle_Make")
        or out.get("vehicle_details")
        or out.get("Registration_Number")
        or out.get("Registration_No")
    )
    out["found"] = not no_vahan and has_details
    
    return out


def upstream_lookup(number: str, product_id: int):
    payload = {
        "secret_key": SECRET_KEY,
        "client_key": CLIENT_KEY,
        "RegistrationNumber": number,
        "product_id": product_id,
        "ss_id": 0,
        "source": SOURCE,
        "session_id": "",
    }
    
    max_retries = int(os.environ.get("MAX_RETRIES", "2"))
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            resp = _session().post(UPSTREAM, json=payload, timeout=UPSTREAM_TIMEOUT)
            
            if resp.status_code == 403:
                try:
                    error_text = resp.text.lower()
                    if "recaptcha" in error_text or "quota" in error_text:
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay * (attempt + 1))
                            _local.sess = None
                            continue
                except:
                    pass
                raise RuntimeError(f"Upstream forbidden or captcha gate triggered (HTTP 403): {resp.text[:120]}")
            
            if resp.status_code != 200:
                if resp.status_code in [429, 503, 504] and attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"Upstream error HTTP {resp.status_code}")
            
            try:
                data = resp.json()
                if data.get("status") == "error" or data.get("error"):
                    msg = data.get("message") or data.get("error") or "Unknown API error"
                    # Fast-fail for non-retryable validation or record-not-found errors
                    if any(term in str(msg).lower() for term in ["not found", "no record", "invalid", "does not exist"]):
                        raise ValueError(str(msg))
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    raise RuntimeError(str(msg))
                return data
            except json.JSONDecodeError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                raise RuntimeError("Invalid JSON response from upstream")
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise RuntimeError("Upstream request timeout")
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise RuntimeError("Upstream connection error")
        except ValueError:
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise
    
    raise RuntimeError("Upstream lookup failed after all retries")


def lookup(number: str, product_id: int = 1, use_cache: bool = True):
    norm = normalize_number(number)
    if not is_valid_number(norm):
        raise ValueError("Invalid Indian vehicle registration number")

    key = f"{norm}|{product_id}"
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return hit, True

    with _inflight_lock:
        holder = _inflight.get(key)
        if holder is None:
            holder = {"event": threading.Event(), "result": None, "owner": threading.get_ident()}
            _inflight[key] = holder
            am_owner = True
        else:
            am_owner = False

    if not am_owner:
        holder["event"].wait(timeout=UPSTREAM_TIMEOUT + 5)
        res = holder["result"]
        if isinstance(res, Exception):
            raise res
        return res, False

    t0 = time.time()
    try:
        raw = upstream_lookup(norm, product_id)
        result = clean_upstream(raw)
    except Exception as exc:
        holder["result"] = exc
        raise
    finally:
        holder["event"].set()
        with _inflight_lock:
            _inflight.pop(key, None)

    holder["result"] = result
    if use_cache:
        _cache_set(key, result)
    return result, False


def is_authorized() -> bool:
    # Check 'key' or 'api_key' in query parameters
    provided_key = request.args.get("key") or request.args.get("api_key")
    
    # Check 'X-API-KEY' header or 'Authorization: Bearer <key>'
    if not provided_key:
        provided_key = request.headers.get("X-API-KEY")
    if not provided_key and request.headers.get("Authorization"):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()
            
    # Check JSON body if POST
    if not provided_key and request.is_json:
        body = request.get_json(silent=True) or {}
        provided_key = body.get("key") or body.get("api_key")

    # Check form-encoded body if POST
    if not provided_key and request.form:
        provided_key = request.form.get("key") or request.form.get("api_key")
        
    return bool(provided_key and provided_key.strip() in VALID_API_KEYS)


class StripVercelPrefixMiddleware:
    """
    Normalizes PATH_INFO so Flask routes the actual requested path on Vercel
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        # 1. Check if Vercel passed the real requested path in HTTP_X_MATCHED_PATH or HTTP_X_FORWARDED_PATH
        matched_path = environ.get("HTTP_X_MATCHED_PATH") or environ.get("HTTP_X_FORWARDED_PATH")
        if matched_path:
            clean_path = matched_path.split("?")[0].strip()
            if clean_path and not clean_path.startswith("/api/index"):
                environ["PATH_INFO"] = clean_path
            elif clean_path in ["/api/index.py", "/api/index"]:
                environ["PATH_INFO"] = "/"
        else:
            path = environ.get("PATH_INFO", "")
            for prefix in ["/api/index.py", "/api/index"]:
                if path.startswith(prefix):
                    path = path[len(prefix):] or "/"
                    environ["PATH_INFO"] = path
                    break
        return self.wsgi_app(environ, start_response)


app.wsgi_app = StripVercelPrefixMiddleware(app.wsgi_app)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-KEY"
    return response


@app.route("/")
@app.route("/api")
@app.route("/api/index")
@app.route("/api/index.py")
def index():
    return jsonify({"message": "VEHICLE API WORKING"}), 200


@app.route("/vehicle", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/vehicle", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/index/vehicle", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/index.py/vehicle", methods=["GET", "POST", "OPTIONS"])
def vehicle_info():
    if request.method == "OPTIONS":
        return "", 204

    # 1. Protect route with API key check
    if not is_authorized():
        return jsonify({
            "status": "error",
            "error": "Unauthorized",
            "message": "Invalid or missing API key. Usage: /vehicle?key={api_key}&query={vehicle_number}"
        }), 401

    json_body = request.get_json(silent=True) or {} if request.method == "POST" and request.is_json else {}
    form_body = request.form if request.form else {}

    # 2. Support 'query' (and aliases: 'quiry', 'number', 'search_term', 'reg_no')
    number = (
        request.args.get("query")
        or request.args.get("quiry")
        or request.args.get("number")
        or request.args.get("search_term")
        or request.args.get("reg_no")
        or json_body.get("query")
        or json_body.get("quiry")
        or json_body.get("number")
        or json_body.get("search_term")
        or json_body.get("reg_no")
        or form_body.get("query")
        or form_body.get("quiry")
        or form_body.get("number")
        or form_body.get("search_term")
        or form_body.get("reg_no")
    )

    try:
        raw_product_id = (
            request.args.get("product_id")
            or json_body.get("product_id")
            or form_body.get("product_id")
            or 1
        )
        product_id = int(raw_product_id)
    except (ValueError, TypeError):
        product_id = 1
    product_id = max(1, min(product_id, 12))
    
    cache_arg = (
        request.args.get("cache")
        or json_body.get("cache")
        or form_body.get("cache")
        or "yes"
    )
    use_cache = str(cache_arg).lower() != "no"

    if not number:
        return jsonify({
            "status": "error",
            "error": "Missing search term",
            "message": "Missing 'query' parameter. Usage: /vehicle?key={api_key}&query={vehicle_number}"
        }), 400

    norm = normalize_number(str(number))
    if not is_valid_number(norm):
        return jsonify({
            "status": "error",
            "error": "Invalid registration number",
            "message": f"'{number}' is not a valid Indian vehicle registration number format."
        }), 400

    try:
        result, cached = lookup(norm, product_id, use_cache)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"status": "error", "error": f"Upstream lookup failed: {exc}"}), 502

    return jsonify(result)


@app.route("/health")
@app.route("/api/health")
@app.route("/api/index/health")
@app.route("/api/index.py/health")
def health():
    return jsonify({
        "status": "ok",
        "cache_entries": len(_cache),
        "uptime_s": int(time.time() - _boot)
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Vehicle API server on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)