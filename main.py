import hashlib
import hmac
import requests
import time
import json
from flask import Flask, request, jsonify
import logging
from datetime import datetime
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Delta Exchange API Configuration
BASE_URL = 'https://api.india.delta.exchange'
API_KEY = 'NWczUdbI9vVbBlCASC0rRFolMpPM32'  # ⚠️ REPLACE WITH YOUR ACTUAL API KEY
API_SECRET = 'YTN79e7x2vuLSYzGW7YUBMnZNJEXTDPxsMaEpH0ZwXptQRwl9zjEby0Z8oAp'  # ⚠️ REPLACE WITH YOUR ACTUAL API SECRET

# Telegram Configuration
TELEGRAM_BOT_TOKEN = '8068558939:AAHcsThdbt0J1uzI0mT140H9vJXbcaVZ9Jk'  # ⚠️ REPLACE WITH YOUR ACTUAL BOT TOKEN
TELEGRAM_CHAT_ID = '871704959'  # ⚠️ REPLACE WITH YOUR ACTUAL CHAT ID
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

# Trading Configuration
SYMBOL = 'BTCUSD'  # This is correct for BTCUSD.P
PRODUCT_ID = 27  # BTCUSD.P perpetual futures
LOT_SIZE = 0.005

# Global variables
current_position = None
active_orders = {}
pending_orders = {}

def send_telegram_message(message):
    """Send message to Telegram"""
    try:
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
        else:
            logger.error(f"❌ Failed to send Telegram message: {response.text}")
    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")

def log_and_notify(message, level="info"):
    """Log message and send to Telegram"""
    if level == "info":
        logger.info(message)
    elif level == "error":
        logger.error(message)
    elif level == "warning":
        logger.warning(message)
    
    send_telegram_message(message)

def generate_signature(secret, message):
    """Generate HMAC signature for Delta Exchange API"""
    message = bytes(message, 'utf-8')
    secret = bytes(secret, 'utf-8')
    hash = hmac.new(secret, message, hashlib.sha256)
    return hash.hexdigest()

def make_api_request(method, endpoint, payload='', params=None):
    """Make authenticated API request to Delta Exchange"""
    timestamp = str(int(time.time()))
    path = f'/v2{endpoint}'
    url = f'{BASE_URL}{path}'

    logger.info(f"🔍 API CALL → {method} {url}")
    logger.info(f"🔍 Payload → {payload}")
    logger.info(f"🔍 Params  → {params}")

    query_string = ''
    if params:
        query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
        if query_string:
            query_string = '?' + query_string

    signature_data = method + timestamp + path + query_string + payload
    signature = generate_signature(API_SECRET, signature_data)

    headers = {
        'api-key': API_KEY,
        'timestamp': timestamp,
        'signature': signature,
        'User-Agent': 'python-trading-bot',
        'Content-Type': 'application/json'
    }

    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == 'POST':
            response = requests.post(url, headers=headers, data=payload, timeout=30)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers, params=params, timeout=30)

        logger.info(f"Response Status: {response.status_code}")
        logger.info(f"Response Text: {response.text}")

        if response.status_code == 200:
            return response.json()
        else:
            error_msg = f"❌ API Error: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return None

    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Request error: {str(e)}"
        logger.error(error_msg)
        return None

def get_current_price():
    """Get current market price"""
    try:
        ticker_result = make_api_request('GET', f'/products/{PRODUCT_ID}/ticker')
        if ticker_result and ticker_result.get('success'):
            current_price = float(ticker_result['result']['mark_price'])
            logger.info(f"📊 Current price: ${current_price}")
            return current_price
        return None
    except Exception as e:
        logger.error(f"❌ Error getting current price: {e}")
        return None

def get_order_status(order_id):
    """Get order status by order ID"""
    result = make_api_request('GET', f'/orders/{order_id}')
    if result and result.get('success'):
        return result.get('result')
    return None

def get_position_data():
    """Get position data"""
    try:
        params = {"product_id": PRODUCT_ID}
        result = make_api_request('GET', '/positions', params=params)
        
        if result and result.get('success'):
            position_data = result.get('result')
            if position_data and position_data.get('size', 0) != 0:
                return position_data
        
        # Fallback to margined positions
        params = {"product_ids": str(PRODUCT_ID)}
        result = make_api_request('GET', '/positions/margined', params=params)
        
        if result and result.get('success'):
            positions = result.get('result', [])
            for pos in positions:
                if (pos.get('product_symbol') == SYMBOL or pos.get('product_id') == PRODUCT_ID) and pos.get('size', 0) != 0:
                    return pos
        
        return None
    except Exception as e:
        logger.error(f"❌ Error getting position data: {e}")
        return None

def place_entry_order(side, entry_price, size):
    """Place limit order for entry with proper validation"""
    try:
        current_price = get_current_price()
        contracts = max(1, int(size * 1000))
        formatted_price = f"{float(entry_price):.2f}"

        # Validate price direction
        if side.lower() == 'buy' and current_price and entry_price <= current_price:
            log_and_notify(f"⚠️ Buy limit price (${entry_price}) must be above current price (${current_price})", "warning")
            return None
        elif side.lower() == 'sell' and current_price and entry_price >= current_price:
            log_and_notify(f"⚠️ Sell limit price (${entry_price}) must be below current price (${current_price})", "warning")
            return None

        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "limit_order",
            "limit_price": formatted_price,
            "time_in_force": "gtc"
        }
        
        log_and_notify(f"🧾 Placing {side} limit order at ${formatted_price}")
        payload = json.dumps(order_data)
        result = make_api_request('POST', '/orders', payload)

        if result and result.get('success'):
            order_id = result['result']['id']
            message = f"✅ *{side.upper()} LIMIT ORDER PLACED*\n" \
                     f"💰 Price: `${formatted_price}`\n" \
                     f"📏 Size: `{contracts}` contracts\n" \
                     f"🆔 Order ID: `{order_id}`\n" \
                     f"⏳ Auto-cancel in 90 minutes if not filled"
            log_and_notify(message)
            return order_id
        else:
            error_msg = f"❌ *FAILED TO PLACE {side.upper()} ORDER*\n" \
                       f"💰 Price: `${formatted_price}`\n" \
                       f"📏 Size: `{contracts}` contracts\n" \
                       f"🚨 Error: `{result.get('error', 'Unknown error') if result else 'No response'}`"
            log_and_notify(error_msg, "error")
            return None
    except Exception as e:
        error_msg = f"❌ *ORDER PLACEMENT ERROR*\n" \
                   f"🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return None

def place_market_order(side, size):
    """Place market order for exits"""
    try:
        contracts = max(1, int(size * 1000))
        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "market_order",
            "time_in_force": "ioc"
        }
        
        log_and_notify(f"⚡ Placing {side} market order")
        payload = json.dumps(order_data)
        result = make_api_request('POST', '/orders', payload)

        if result and result.get('success'):
            order_id = result['result']['id']
            message = f"✅ *{side.upper()} MARKET ORDER EXECUTED*\n" \
                     f"📏 Size: `{contracts}` contracts\n" \
                     f"🆔 Order ID: `{order_id}`"
            log_and_notify(message)
            return order_id
        else:
            error_msg = f"❌ *FAILED TO EXECUTE {side.upper()} MARKET ORDER*\n" \
                       f"📏 Size: `{contracts}` contracts\n" \
                       f"🚨 Error: `{result.get('error', 'Unknown error') if result else 'No response'}`"
            log_and_notify(error_msg, "error")
            return None
    except Exception as e:
        error_msg = f"❌ *MARKET ORDER ERROR*\n" \
                   f"🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return None

def monitor_order(order_id, side, entry_price, stop_loss, size):
    """Monitor order for 90 minutes and cancel if not filled"""
    max_wait = 5400  # 90 minutes in seconds
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            order_status = get_order_status(order_id)
            if not order_status:
                time.sleep(10)
                continue

            state = order_status.get('state')
            filled = order_status.get('size_filled', 0)
            
            if state == 'filled':
                message = f"✅ *ORDER FILLED*\n" \
                         f"🆔 Order ID: `{order_id}`\n" \
                         f"📏 Filled: `{filled}` contracts"
                log_and_notify(message)
                return True
            elif state in ['cancelled', 'rejected']:
                message = f"❌ *ORDER {state.upper()}*\n" \
                         f"🆔 Order ID: `{order_id}`"
                log_and_notify(message, "warning")
                return False
            
            # Send update every 5 minutes
            if int(time.time() - start_time) % 300 == 0:
                remaining = (max_wait - (time.time() - start_time)) / 60
                message = f"⏳ *ORDER PENDING*\n" \
                         f"🆔 Order ID: `{order_id}`\n" \
                         f"📏 Filled: `{filled}` contracts\n" \
                         f"⏱️ Auto-cancel in {int(remaining)} minutes"
                log_and_notify(message)
            
            time.sleep(10)
        except Exception as e:
            logger.error(f"Error monitoring order: {e}")
            time.sleep(10)
    
    # Timeout reached - cancel order
    message = f"⏰ *ORDER TIMEOUT - CANCELLING*\n" \
             f"🆔 Order ID: `{order_id}`"
    log_and_notify(message, "warning")
    make_api_request('DELETE', f'/orders/{order_id}')
    return False

def cancel_all_orders():
    """Cancel all open orders"""
    try:
        params = {"product_ids": str(PRODUCT_ID), "states": "open"}
        result = make_api_request('GET', '/orders', params=params)

        if result and result.get('success'):
            orders = result.get('result', [])
            for order in orders:
                make_api_request('DELETE', f'/orders/{order["id"]}')
            
            if orders:
                log_and_notify(f"🗑️ Cancelled {len(orders)} orders")
            else:
                logger.info("No orders to cancel")
            
            # Clear pending orders
            global pending_orders
            pending_orders.clear()
    except Exception as e:
        logger.error(f"Error cancelling orders: {e}")

def close_position():
    """Close current position with market order"""
    try:
        position = get_position_data()
        if not position or position.get('size', 0) == 0:
            log_and_notify("ℹ️ No position to close")
            return

        size = abs(position['size'])
        side = 'sell' if position['size'] > 0 else 'buy'
        
        log_and_notify(f"🚪 Closing position: {side.upper()} {size} contracts")
        place_market_order(side, size * 0.001)  # Convert to BTC size
    except Exception as e:
        error_msg = f"❌ *POSITION CLOSE ERROR*\n" \
                   f"🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle TradingView webhook alerts"""
    global current_position, pending_orders

    try:
        data = request.get_json()
        logger.info(f"📨 Received alert: {json.dumps(data)}")

        alert_type = data.get('alert_type')
        entry_price = float(data.get('entry_price', 0))
        stop_loss = float(data.get('stop_loss', 0))
        size = float(data.get('lot_size', LOT_SIZE))

        current_price = get_current_price()

        if alert_type == 'LONG_ENTRY':
            log_and_notify(f"🟢 LONG ENTRY SIGNAL\n💰 {entry_price} | 🛑 {stop_loss}")
            cancel_all_orders()
            order_id = place_entry_order('buy', entry_price, size)
            if order_id:
                current_position = 'long_pending'
                pending_orders[order_id] = {
                    'type': 'entry',
                    'side': 'buy',
                    'price': entry_price,
                    'size': size,
                    'stop_loss': stop_loss
                }
                # Start monitoring thread
                threading.Thread(
                    target=monitor_order,
                    args=(order_id, 'buy', entry_price, stop_loss, size),
                    daemon=True
                ).start()

        elif alert_type == 'SHORT_ENTRY':
            log_and_notify(f"🔴 SHORT ENTRY SIGNAL\n💰 {entry_price} | 🛑 {stop_loss}")
            cancel_all_orders()
            order_id = place_entry_order('sell', entry_price, size)
            if order_id:
                current_position = 'short_pending'
                pending_orders[order_id] = {
                    'type': 'entry',
                    'side': 'sell',
                    'price': entry_price,
                    'size': size,
                    'stop_loss': stop_loss
                }
                # Start monitoring thread
                threading.Thread(
                    target=monitor_order,
                    args=(order_id, 'sell', entry_price, stop_loss, size),
                    daemon=True
                ).start()

        elif alert_type in ['LONG_EXIT', 'SHORT_EXIT']:
            log_and_notify(f"🚪 {alert_type.replace('_', ' ')} SIGNAL")
            close_position()
            current_position = None

        return jsonify({"status": "success"})

    except Exception as e:
        error_msg = f"❌ *WEBHOOK ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cancel_all', methods=['POST'])
def cancel_all_endpoint():
    """Manual endpoint to cancel all orders"""
    try:
        cancel_all_orders()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/close_position', methods=['POST'])
def close_position_endpoint():
    """Manual endpoint to close position"""
    try:
        close_position()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Get bot status and send to Telegram"""
    position = get_position_data()
    current_price = get_current_price()
    pending = len(pending_orders)

    status_info = {
        "status": "running",
        "position": position,
        "pending_orders": pending_orders,
        "current_price": current_price
    }

    # Format Telegram message
    message = f"📊 *BOT STATUS CHECKED*\n" \
              f"📍 Position: `{position if position else 'None'}`\n" \
              f"📋 Pending Orders: `{pending}`\n" \
              f"💰 Current Price: `${current_price}`"

    log_and_notify(message)  # Logs + Telegram both

    return jsonify(status_info)


    # Start Flask app
    app.run(host='0.0.0.0', port=5000, debug=False)
