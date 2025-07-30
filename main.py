import hashlib
import hmac
import requests
import time
import json
from flask import Flask, request, jsonify
import logging
from datetime import datetime
import threading
import traceback
from typing import Dict, Any, Optional, Tuple

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ⚠️ REPLACE WITH YOUR ACTUAL CREDENTIALS ⚠️
# Delta Exchange API Configuration
BASE_URL = 'https://api.india.delta.exchange'
API_KEY = 'NWczUdbI9vVbBlCASC0rRFolMpPM32'  # 🔑 Replace with your actual API key
API_SECRET = 'YTN79e7x2vuLSYzGW7YUBMnZNJEXTDPxsMaEpH0ZwXptQRwl9zjEby0Z8oAp'  # 🔑 Replace with your actual API secret

# Telegram Configuration  
TELEGRAM_BOT_TOKEN = '8068558939:AAHcsThdbt0J1uzI0mT140H9vJXbcaVZ9Jk'  # 🤖 Replace with your bot token
TELEGRAM_CHAT_ID = '871704959'  # 💬 Replace with your chat ID
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

# Trading Configuration
SYMBOL = 'BTCUSD'
PRODUCT_ID = 27
LOT_SIZE = 0.005

# Enhanced Configuration
MAX_RETRIES = 3
RETRY_DELAY = 1
REQUEST_TIMEOUT = (5, 30)

# Global variables
current_position = None
active_orders = {}

def send_telegram_message(message):
    """Enhanced Telegram messaging with error handling"""
    try:
        if TELEGRAM_BOT_TOKEN == 'your_telegram_bot_token_here':
            return False
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"🤖 Delta Trading Bot\n⏰ {timestamp}\n\n{message}"

        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': full_message,
            'parse_mode': 'Markdown'
        }

        response = requests.post(TELEGRAM_API_URL, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("✅ Telegram message sent successfully")
            return True
        else:
            logger.warning(f"⚠️ Telegram failed: {response.status_code}")
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram error: {str(e)}")
        return False

def log_and_notify(message, level="info", request_id=None):
    """Enhanced logging with request tracking"""
    log_message = f"[{request_id}] {message}" if request_id else message
    
    if level == "info":
        logger.info(log_message)
    elif level == "error":
        logger.error(log_message)
    elif level == "warning":
        logger.warning(log_message)
    elif level == "critical":
        logger.critical(log_message)
    
    # Send to Telegram (async to avoid blocking)
    threading.Thread(target=send_telegram_message, args=(message,), daemon=True).start()

def generate_signature(secret, message):
    """Generate HMAC signature for Delta Exchange API"""
    try:
        message = bytes(message, 'utf-8')
        secret = bytes(secret, 'utf-8')
        hash_obj = hmac.new(secret, message, hashlib.sha256)
        return hash_obj.hexdigest()
    except Exception as e:
        logger.error(f"❌ Signature generation failed: {str(e)}")
        raise

def make_api_request(method, endpoint, payload='', params=None) -> Tuple[bool, Optional[Dict]]:
    """Enhanced API request with comprehensive error handling"""
    request_id = f"REQ_{int(time.time() * 1000)}"
    
    logger.info(f"🚀 [{request_id}] {method} {endpoint}")
    
    timestamp = str(int(time.time()))
    path = f'/v2{endpoint}'
    url = f'{BASE_URL}{path}'

    query_string = ''
    if params:
        query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
        if query_string:
            query_string = '?' + query_string

    signature_data = method + timestamp + path + query_string + payload
    
    try:
        signature = generate_signature(API_SECRET, signature_data)
    except Exception as e:
        logger.error(f"❌ [{request_id}] Signature generation failed: {str(e)}")
        return False, {"error": "Signature generation failed", "details": str(e)}

    headers = {
        'api-key': API_KEY,
        'timestamp': timestamp,
        'signature': signature,
        'User-Agent': 'delta-trading-bot/4.0',
        'Content-Type': 'application/json'
    }

    # Retry mechanism
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"🔄 [{request_id}] Attempt {attempt + 1}/{MAX_RETRIES}")
            
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            elif method == 'POST':
                response = requests.post(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
            else:
                logger.error(f"❌ [{request_id}] Unsupported method: {method}")
                return False, {"error": "Unsupported HTTP method"}

            logger.info(f"📥 [{request_id}] Status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    logger.info(f"✅ [{request_id}] Request successful")
                    return True, response_data
                except json.JSONDecodeError as e:
                    logger.error(f"❌ [{request_id}] JSON decode error: {str(e)}")
                    return False, {"error": "Invalid JSON response", "raw_response": response.text}
            
            else:
                error_data = {
                    "statuscode": response.status_code,
                    "reason": response.reason,
                    "rawresponse": response.text
                }
                
                try:
                    error_json = response.json()
                    error_data.update(error_json)
                except:
                    pass
                
                logger.error(f"❌ [{request_id}] HTTP Error {response.status_code}: {response.text}")
                
                # Don't retry on client errors (4xx)
                if 400 <= response.status_code < 500:
                    return False, error_data
                
                # Retry on server errors (5xx)
                if attempt < MAX_RETRIES - 1:
                    logger.warning(f"⏳ [{request_id}] Retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                    continue
                
                return False, error_data

        except requests.exceptions.Timeout as e:
            logger.error(f"⏰ [{request_id}] Timeout error: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return False, {"error": "Request timeout", "details": str(e)}

        except requests.exceptions.ConnectionError as e:
            logger.error(f"🔌 [{request_id}] Connection error: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return False, {"error": "Connection error", "details": str(e)}

        except Exception as e:
            logger.error(f"💥 [{request_id}] Unexpected error: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return False, {"error": "Unexpected error", "details": str(e)}

    return False, {"error": "Max retries exceeded"}

def cancel_all_orders():
    """Cancel all open orders using Delta Exchange API"""
    try:
        log_and_notify("❎ Cancelling all open orders...")
        
        # Use the correct Delta Exchange API format
        payload = json.dumps({
            "product_id": PRODUCT_ID,
            "cancel_limit_orders": "true",
            "cancel_stop_orders": "true",
            "cancel_reduce_only_orders": "true"
        })
        
        success, result = make_api_request('DELETE', '/orders/all', payload)
        
        if success and result and result.get('success'):
            log_and_notify("✅ All open orders cancelled successfully.")
            return True
        else:
            error_details = result.get('error', result) if result else 'No response'
            log_and_notify(f"⚠️ Cancel orders response: {error_details}", level="warning")
            return False
            
    except Exception as e:
        log_and_notify(f"❌ ERROR cancelling orders: {str(e)}", level="error")
        return False

def place_stop_market_order(side, trigger_price, size, request_id=None):
    """Place stop-market order (Delta Exchange compatible)"""
    try:
        contracts = max(1, int(size * 1000))  # Convert BTC to contracts
        trigger_price = float(trigger_price)
        formatted_trigger = f"{trigger_price:.1f}"  # Delta uses 0.5 tick size
        
        # Ensure price is aligned to tick size (0.5)
        aligned_price = round(trigger_price * 2) / 2
        formatted_trigger = f"{aligned_price:.1f}"
        
        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "market_order",
            "stop_order_type": "stop_loss_order",
            "stop_price": formatted_trigger,
            "stop_trigger_method": "last_traded_price"
        }

        log_and_notify(f"📈 Placing {side.upper()} STOP-MARKET order\n"
                      f"🔫 Trigger: ${formatted_trigger}\n"
                      f"📏 Size: {size} BTC ({contracts} contracts)", 
                      request_id=request_id)

        payload = json.dumps(order_data)
        success, result = make_api_request('POST', '/orders', payload)

        if success and result and result.get('success'):
            order_id = result['result']['id']
            order_state = result['result'].get('state', 'unknown')
            
            log_and_notify(
                f"✅ {side.upper()} STOP-MARKET ORDER PLACED\n"
                f"🆔 Order ID: {order_id}\n"
                f"🔫 Trigger: ${formatted_trigger}\n"
                f"📏 Size: {contracts} contracts\n"
                f"📊 State: {order_state}",
                request_id=request_id
            )
            return order_id
        else:
            error_details = result if result else 'No response'
            error_msg = f"❌ FAILED TO PLACE {side.upper()} ORDER\n" \
                       f"🚨 Error: Unknown error\n" \
                       f"📋 Full Response: {json.dumps(error_details, indent=2)}"
            log_and_notify(error_msg, "error", request_id=request_id)
            return None

    except Exception as e:
        error_msg = f"❌ STOP-MARKET ORDER ERROR\n" \
                   f"🚨 Error: {str(e)}"
        log_and_notify(error_msg, "error", request_id=request_id)
        return None

def place_market_order(side, size, request_id=None):
    """Place immediate market order"""
    try:
        contracts = max(1, int(size * 1000))
        
        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "market_order"
        }
        
        log_and_notify(f"⚡ Placing {side.upper()} MARKET order\n"
                      f"📏 Size: {size} BTC ({contracts} contracts)", 
                      request_id=request_id)

        payload = json.dumps(order_data)
        success, result = make_api_request('POST', '/orders', payload)

        if success and result and result.get('success'):
            order_id = result['result']['id']
            order_state = result['result'].get('state', 'unknown')
            filled_size = result['result'].get('size', 0)
            avg_price = result['result'].get('average_fill_price', 'N/A')
            
            log_and_notify(
                f"✅ {side.upper()} MARKET ORDER EXECUTED!\n"
                f"🆔 Order ID: {order_id}\n"
                f"📏 Size: {contracts} contracts\n"
                f"✅ Filled: {filled_size} contracts\n"
                f"💰 Avg Price: ${avg_price}\n"
                f"📊 State: {order_state}",
                request_id=request_id
            )
            return order_id
        else:
            error_details = result if result else 'No response'
            error_msg = f"❌ FAILED TO PLACE {side.upper()} ORDER\n" \
                       f"🚨 Error: Unknown error\n" \
                       f"📋 Full Response: {json.dumps(error_details, indent=2)}"
            log_and_notify(error_msg, "error", request_id=request_id)
            return None

    except Exception as e:
        error_msg = f"❌ MARKET ORDER ERROR\n" \
                   f"🚨 Error: {str(e)}"
        log_and_notify(error_msg, "error", request_id=request_id)
        return None

def get_position_data():
    """Get current position data"""
    try:
        params = {"product_id": PRODUCT_ID}
        success, result = make_api_request('GET', '/positions', params=params)
        
        if success and result and result.get('success'):
            position_data = result.get('result')
            if position_data and position_data.get('size', 0) != 0:
                return position_data
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Error getting position: {str(e)}")
        return None

def close_position():
    """Close current position with market order"""
    try:
        log_and_notify("🔄 Checking for position to close...")
        
        position = get_position_data()
        if position and position.get('size', 0) != 0:
            position_size = int(position['size'])
            side = 'sell' if position_size > 0 else 'buy'
            size = abs(position_size) / 1000.0
            
            log_and_notify(f"📍 Found position: {position_size} contracts")
            log_and_notify(f"🚪 Closing position with {side.upper()} market order")
            
            order_id = place_market_order(side, size)
            if order_id:
                log_and_notify("✅ Position close order placed successfully")
                return True
            else:
                log_and_notify("❌ Failed to place position close order", level="error")
                return False
        else:
            log_and_notify("ℹ️ No open position to close.")
            return True
            
    except Exception as e:
        log_and_notify(f"❌ ERROR closing position: {str(e)}", level="error")
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    """Main webhook handler for TradingView alerts"""
    global current_position, active_orders
    
    webhook_id = f"WH_{int(time.time() * 1000)}"
    start_time = time.time()
    
    logger.info(f"🎯 [{webhook_id}] Webhook request received")

    try:
        # Get data from request
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        logger.info(f"📨 [{webhook_id}] Data: {json.dumps(data, indent=2)}")

        # Validate required fields
        if not data or 'alert_type' not in data:
            error_msg = "❌ Missing alert_type in webhook data"
            log_and_notify(error_msg, "error", webhook_id)
            return jsonify({"status": "error", "message": "Missing alert_type"}), 400

        # Extract parameters
        alert_type = data.get('alert_type')
        stop_price = float(data.get("stop_price", 0)) if data.get("stop_price") else 0
        stop_loss = float(data.get('stop_loss', 0)) if data.get('stop_loss') else 0
        size = float(data.get('lot_size', LOT_SIZE))

        logger.info(f"📊 [{webhook_id}] Alert: {alert_type}, Price: {stop_price}, SL: {stop_loss}, Size: {size}")

        # Process different alert types
        if alert_type == 'LONG_ENTRY':
            log_and_notify(f"🟢 LONG ENTRY SIGNAL\n"
                          f"🔫 Stop: {stop_price} | 🛑 SL: {stop_loss}", 
                          request_id=webhook_id)
            
            cancel_all_orders()
            
            if stop_price > 0:
                # Place stop-market buy order
                order_id = place_stop_market_order('buy', stop_price, size, webhook_id)
                if order_id:
                    current_position = 'long_pending'
                    active_orders[order_id] = {
                        'type': 'entry',
                        'side': 'buy',
                        'trigger_price': stop_price,
                        'size': size
                    }
            else:
                # Place immediate market buy order
                order_id = place_market_order('buy', size, webhook_id)
                if order_id:
                    current_position = 'long'

        elif alert_type == 'SHORT_ENTRY':
            log_and_notify(f"🔴 SHORT ENTRY SIGNAL\n"
                          f"🔫 Stop: {stop_price} | 🛑 SL: {stop_loss}", 
                          request_id=webhook_id)
            
            cancel_all_orders()
            
            if stop_price > 0:
                # Place stop-market sell order
                order_id = place_stop_market_order('sell', stop_price, size, webhook_id)
                if order_id:
                    current_position = 'short_pending'
                    active_orders[order_id] = {
                        'type': 'entry',
                        'side': 'sell',
                        'trigger_price': stop_price,
                        'size': size
                    }
            else:
                # Place immediate market sell order
                order_id = place_market_order('sell', size, webhook_id)
                if order_id:
                    current_position = 'short'

        elif alert_type in ['LONG_EXIT', 'SHORT_EXIT']:
            log_and_notify(f"🚪 {alert_type.replace('_', ' ')} SIGNAL", 
                          request_id=webhook_id)
            cancel_all_orders()
            close_position()
            current_position = None
            active_orders.clear()

        else:
            error_msg = f"❌ Unknown alert_type: {alert_type}"
            log_and_notify(error_msg, "error", webhook_id)
            return jsonify({"status": "error", "message": error_msg}), 400

        processing_time = time.time() - start_time
        logger.info(f"✅ [{webhook_id}] Processed in {processing_time:.3f}s")

        return jsonify({
            "status": "success",
            "webhook_id": webhook_id,
            "processing_time": processing_time,
            "alert_type": alert_type
        })

    except Exception as e:
        processing_time = time.time() - start_time
        error_msg = f"❌ WEBHOOK ERROR: {str(e)}"
        log_and_notify(error_msg, "critical", webhook_id)
        logger.error(f"📋 Traceback: {traceback.format_exc()}")
        
        return jsonify({
            "status": "error", 
            "message": str(e),
            "webhook_id": webhook_id,
            "processing_time": processing_time
        }), 500

@app.route('/status', methods=['GET'])
def status():
    """Bot status endpoint"""
    try:
        position = get_position_data()
        
        return jsonify({
            "status": "running",
            "timestamp": datetime.now().isoformat(),
            "current_position": current_position,
            "position_data": position,
            "active_orders": len(active_orders),
            "symbol": SYMBOL,
            "product_id": PRODUCT_ID,
            "lot_size": LOT_SIZE
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "4.0"
    })

@app.route('/test', methods=['GET'])
def test_api():
    """Test API connection"""
    try:
        success, result = make_api_request('GET', f'/products/{PRODUCT_ID}')
        if success:
            return jsonify({
                "status": "success",
                "message": "API connection working",
                "product_data": result
            })
        else:
            return jsonify({
                "status": "error",
                "message": "API connection failed",
                "error": result
            }), 500
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# Startup notification
if __name__ == '__main__':
    try:
        logger.info("🚀 Delta Trading Bot v4.0 Starting...")
        logger.info(f"📊 Symbol: {SYMBOL}")
        logger.info(f"🆔 Product ID: {PRODUCT_ID}")
        logger.info(f"📏 Default Lot Size: {LOT_SIZE} BTC")
        
        # Test API connection on startup
        success, result = make_api_request('GET', f'/products/{PRODUCT_ID}')
        if success:
            logger.info("✅ API connection verified successfully")
            send_telegram_message("🚀 Delta Trading Bot v4.0 Started!\n✅ API Connection Verified")
        else:
            logger.error(f"❌ API connection failed: {result}")
            send_telegram_message("❌ Delta Trading Bot startup failed!\n🚨 API Connection Error")
        

        
    except Exception as e:
        logger.error(f"❌ Startup error: {str(e)}")
        send_telegram_message(f"❌ Bot startup failed: {str(e)}")
        # 🌐 Start Flask + Background Bot together
if __name__ == "__main__":
    import threading
    import time

    # 🔁 Flask webhook server
    def run_flask():
        app.run(host="0.0.0.0", port=5000)

    # ♻️ Background monitoring loop (price, orders, etc.)
    def run_bot_loop():
        while True:
            logger.info("🔄 Background monitor running...")
            # Your live trading checks go here (e.g., check_price(), check_status(), etc.)
            time.sleep(10)

    # Start both simultaneously
    threading.Thread(target=run_flask).start()
    run_bot_loop()

