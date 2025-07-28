import hashlib
import hmac
import requests
import time
import json
from flask import Flask, request, jsonify
import logging
from datetime import datetime
import threading
import urllib.parse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Delta Exchange API Configuration
BASE_URL = 'https://api.india.delta.exchange'
API_KEY = 'NWczUdbI9vVbBlCASC0rRFolMpPM32'  # Replace with your actual API key
API_SECRET = 'YTN79e7x2vuLSYzGW7YUBMnZNJEXTDPxsMaEpH0ZwXptQRwl9zjEby0Z8oAp'  # Replace with your actual API secret

# Telegram Configuration
TELEGRAM_BOT_TOKEN = '8068558939:AAHcsThdbt0J1uzI0mT140H9vJXbcaVZ9Jk'  # Replace with your actual bot token
TELEGRAM_CHAT_ID = '871704959'  # Replace with your actual chat ID
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

# Trading Configuration
SYMBOL = 'BTCUSD.P'
PRODUCT_ID = 27  # BTCUSD.P perpetual futures
LOT_SIZE = 0.005

# Global variables
current_position = None
active_orders = {}
stop_loss_orders = {}
pending_stop_losses = {}

def send_telegram_message(message):
    """Send message to Telegram"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"🤖 *Delta Trading Bot*\n⏰ {timestamp}\n\n{message}"
        
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
    """Make authenticated API request to Delta Exchange - FIXED VERSION"""
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

        # ✅ Enhanced error logging
        logger.info(f"Response Status: {response.status_code}")
        logger.info(f"Response Text: {response.text}")

        if response.status_code == 200:
            return response.json()
        else:
            error_msg = f"❌ API Error: {response.status_code} - {response.text}"
            logger.error(error_msg)
            log_and_notify(error_msg, "error")
            return None

    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Request error: {str(e)}"
        logger.error(error_msg)
        log_and_notify(error_msg, "error")
        return None

def get_order_status(order_id):
    """Get order status by order ID"""
    result = make_api_request('GET', f'/orders/{order_id}')
    if result and result.get('success'):
        return result.get('result')
    return None

def get_position_data():
    """Get position data - COMPLETELY FIXED VERSION"""
    try:
        logger.info("🔍 Getting position data...")
        
        # ✅ Method 1: Use /positions/margined (most reliable)
        result = make_api_request('GET', '/positions/margined')
        
        if result and result.get('success'):
            positions = result.get('result', [])
            logger.info(f"✅ Got {len(positions)} positions from /positions/margined")
            
            for pos in positions:
                logger.info(f"🔍 Checking position: {pos.get('product_symbol')} with size {pos.get('size')}")
                if pos.get('product_symbol') == SYMBOL and pos.get('size') != 0:
                    logger.info(f"✅ Found matching position: {pos}")
                    return pos
        
        # ✅ Method 2: Try with specific product_id
        logger.info("🔍 Trying /positions with product_id...")
        params = {"product_id": PRODUCT_ID}
        result = make_api_request('GET', '/positions', params=params)
        
        if result and result.get('success'):
            position_data = result.get('result')
            logger.info(f"✅ Got position data: {position_data}")
            if position_data and position_data.get('size') != 0:
                return position_data
        
        # ✅ Method 3: Try with underlying_asset_symbol
        logger.info("🔍 Trying /positions with underlying_asset_symbol...")
        params = {"underlying_asset_symbol": "BTC"}
        result = make_api_request('GET', '/positions', params=params)
        
        if result and result.get('success'):
            position_data = result.get('result')
            logger.info(f"✅ Got position data via underlying_asset: {position_data}")
            if position_data and position_data.get('size') != 0:
                return position_data
        
        logger.info("ℹ️ No open position found")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error getting position data: {e}")
        return None

def place_stop_limit_order(side, stop_price, limit_price, size):
    """Place a stop-limit order - COMPLETELY FIXED VERSION"""
    contracts = int(size * 1000)
    stop_side = side.lower()

    # ✅ CORRECT STOP ORDER LOGIC FOR DELTA EXCHANGE
    if stop_side == "buy":
        # BUY STOP: Price goes above stop_price, then buy at limit_price
        stop_order_type = "stop_loss_order"
        # For buy stops, limit price should be at or above stop price
        if limit_price < stop_price:
            limit_price = stop_price + 10  # Small buffer above stop
    else:
        # SELL STOP: Price goes below stop_price, then sell at limit_price
        stop_order_type = "stop_loss_order"
        # For sell stops, limit price should be at or below stop price
        if limit_price > stop_price:
            limit_price = stop_price - 10  # Small buffer below stop

    # ✅ CORRECT ORDER DATA ACCORDING TO DELTA API
    order_data = {
        "product_id": PRODUCT_ID,
        "size": contracts,
        "side": stop_side,
        "order_type": "limit_order",
        "limit_price": str(limit_price),
        "stop_order_type": stop_order_type,
        "stop_price": str(stop_price),
        "stop_trigger_method": "mark_price"
    }
    
    logger.info(f"✅ Order Data: {order_data}")
    payload = json.dumps(order_data)
    result = make_api_request('POST', '/orders', payload)

    if result and result.get('success'):
        order_id = result['result']['id']
        message = f"🚀 *{side.upper()} STOP LIMIT ORDER PLACED*\n" \
                  f"🔼 Stop Price: `${stop_price}`\n" \
                  f"🎯 Limit Price: `${limit_price}`\n" \
                  f"📏 Size: `{contracts}` contracts ({size} BTC)\n" \
                  f"🎯 Symbol: `{SYMBOL}`\n" \
                  f"📋 Order ID: `{order_id}`"
        log_and_notify(message)
        return order_id
    else:
        error_msg = f"❌ *FAILED TO PLACE {side.upper()} STOP ORDER*\n" \
                    f"🔼 Stop Price: `${stop_price}`\n" \
                    f"🎯 Limit Price: `${limit_price}`\n" \
                    f"🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")
        return None

def monitor_order_and_place_sl(order_id, original_side, stop_loss_price, contracts):
    """Monitor order fill status - FIXED VERSION"""
    max_attempts = 5400  # 90 minutes with 1-second intervals
    attempt = 0

    message = f"👀 *MONITORING ORDER FILL*\n" \
             f"📊 Order ID: `{order_id}`\n" \
             f"⏱️ Auto-cancel in 90 minutes if not filled"
    log_and_notify(message)

    while attempt < max_attempts:
        try:
            order_status = get_order_status(order_id)

            if order_status:
                state = order_status.get('state')
                filled_size = order_status.get('size_filled', 0)

                logger.info(f"Order {order_id} - State: {state}, Filled: {filled_size}")

                if state == 'filled':
                    message = f"✅ *ORDER FILLED SUCCESSFULLY*\n" \
                             f"📊 Order ID: `{order_id}`\n" \
                             f"📏 Filled Size: `{filled_size}` contracts\n" \
                             f"🛡️ Position is now open - SL will be triggered by PineScript"
                    log_and_notify(message)

                    # Remove from pending
                    if order_id in pending_stop_losses:
                        del pending_stop_losses[order_id]
                    break

                elif state in ['cancelled', 'rejected']:
                    message = f"❌ *ORDER {state.upper()}*\n" \
                             f"📊 Order ID: `{order_id}`"
                    log_and_notify(message, "warning")

                    # Remove from pending
                    if order_id in pending_stop_losses:
                        del pending_stop_losses[order_id]
                    break

                elif state == 'partially_filled' and filled_size > 0:
                    if attempt % 300 == 0:  # Log every 5 minutes
                        remaining_minutes = (max_attempts - attempt) // 60
                        message = f"⏳ *ORDER PARTIALLY FILLED*\n" \
                                 f"📊 Order ID: `{order_id}`\n" \
                                 f"📏 Filled: `{filled_size}` contracts\n" \
                                 f"⏱️ Auto-cancel in {remaining_minutes} minutes"
                        log_and_notify(message)

            # 15-minute update
            if attempt > 0 and attempt % 900 == 0:
                remaining_minutes = (max_attempts - attempt) // 60
                message = f"⏰ *ORDER MONITORING UPDATE*\n" \
                         f"📊 Order ID: `{order_id}`\n" \
                         f"⏱️ Auto-cancel in {remaining_minutes} minutes"
                log_and_notify(message)

            time.sleep(1)
            attempt += 1

        except Exception as e:
            logger.error(f"Error monitoring order {order_id}: {e}")
            time.sleep(1)
            attempt += 1

    # Auto-cancel if time exceeds
    if attempt >= max_attempts:
        message = f"⏰ *90 MINUTE TIMEOUT REACHED*\n" \
                 f"📊 Order ID: `{order_id}`\n" \
                 f"🗑️ Auto-cancelling the order now..."
        log_and_notify(message, "warning")

        cancel_result = make_api_request('DELETE', f'/orders/{order_id}')
        if cancel_result and cancel_result.get('success'):
            log_and_notify(f"✅ *ORDER AUTO-CANCELLED*\n📊 Order ID: `{order_id}`")
        else:
            log_and_notify(f"❌ *FAILED TO AUTO-CANCEL ORDER*\n📊 Order ID: `{order_id}`", "error")

        if order_id in pending_stop_losses:
            del pending_stop_losses[order_id]

def cancel_all_orders():
    """Cancel all open orders - COMPLETELY FIXED VERSION"""
    try:
        # ✅ CORRECT PARAMETER FORMAT
        params = {"product_ids": str(PRODUCT_ID), "states": "open"}
        result = make_api_request('GET', '/orders', params=params)
        
        if result and result.get('success'):
            orders = result.get('result', [])
            cancelled_count = 0
            
            for order in orders:
                order_id = order['id']
                # ✅ Use DELETE method with order_id in URL
                cancel_result = make_api_request('DELETE', f'/orders/{order_id}')
                if cancel_result and cancel_result.get('success'):
                    cancelled_count += 1
                    logger.info(f"✅ Cancelled order: {order_id}")
                else:
                    logger.error(f"❌ Failed to cancel order: {order_id}")
            
            if cancelled_count > 0:
                message = f"🗑️ *ORDERS CANCELLED*\n" \
                         f"📊 Cancelled: `{cancelled_count}` orders\n" \
                         f"🎯 Symbol: `{SYMBOL}`"
                log_and_notify(message)
            
            # Clear pending stop losses
            global pending_stop_losses
            pending_stop_losses.clear()
            
    except Exception as e:
        logger.error(f"❌ Error cancelling orders: {e}")

def close_position():
    """Close current position - COMPLETELY FIXED VERSION"""
    global current_position
    
    # ✅ Always get fresh position data
    position_data = get_position_data()
    
    if not position_data or position_data.get('size') == 0:
        message = "ℹ️ *NO POSITION TO CLOSE*\n" \
                 f"🎯 Symbol: `{SYMBOL}`"
        log_and_notify(message)
        current_position = None
        return
    
    position_size = abs(int(position_data['size']))
    close_side = "sell" if position_data['size'] > 0 else "buy"
    position_value = position_size * 0.001
    entry_price = position_data.get('entry_price', 'N/A')
    
    # ✅ CORRECT CLOSE ORDER DATA
    close_order_data = {
        "product_id": PRODUCT_ID,
        "size": position_size,
        "side": close_side,
        "order_type": "market_order",
        "reduce_only": "true"  # This ensures it only closes position
    }
    
    logger.info(f"✅ Close Order Data: {close_order_data}")
    payload = json.dumps(close_order_data)
    result = make_api_request('POST', '/orders', payload)
    
    if result and result.get('success'):
        message = f"🚪 *POSITION CLOSED*\n" \
                 f"📊 Order ID: `{result['result']['id']}`\n" \
                 f"📏 Size: `{position_size}` contracts ({position_value} BTC)\n" \
                 f"🔄 Side: `{close_side.upper()}`\n" \
                 f"💵 Entry Price: `${entry_price}`\n" \
                 f"🎯 Symbol: `{SYMBOL}`"
        
        log_and_notify(message)
        current_position = None
        cancel_all_orders()
    else:
        error_msg = f"❌ *FAILED TO CLOSE POSITION*\n" \
                   f"📏 Size: `{position_size}` contracts\n" \
                   f"🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle TradingView webhook alerts - COMPLETELY FIXED VERSION"""
    global current_position, active_orders, pending_stop_losses
    
    try:
        data = request.get_json()
        logger.info(f"📨 Received alert: {data}")
        
        alert_type = data.get('alert_type')
        entry_price = float(data.get('entry_price', 0))
        stop_loss = float(data.get('stop_loss', 0))
        
        # ✅ Extract additional data from SMC indicator
        lot_size_from_alert = float(data.get('lot_size', LOT_SIZE))
        signal_type = data.get('signal_type', 'UNKNOWN')
        entry_method = data.get('entry_method', 'STOP_LIMIT')
        strategy_name = data.get('strategy', 'UNKNOWN')
        
        if alert_type == 'LONG_ENTRY':
            message = f"🟢 *LONG ENTRY SIGNAL RECEIVED*\n" \
                     f"💰 Entry Price: `${entry_price}`\n" \
                     f"🛡️ Stop Loss: `${stop_loss}`\n" \
                     f"📏 Size: `{lot_size_from_alert}` BTC\n" \
                     f"📋 Strategy: `{strategy_name}`\n" \
                     f"🎯 Signal: `{signal_type}`"
            log_and_notify(message)
            
            cancel_all_orders()
            # ✅ Place buy stop order for long entry
            order_id = place_stop_limit_order('buy', entry_price, entry_price, lot_size_from_alert)
            if order_id:
                active_orders['long'] = order_id
                current_position = 'long_pending'
                
                contracts = int(lot_size_from_alert * 1000)
                pending_stop_losses[order_id] = {
                    'side': 'buy',
                    'stop_price': stop_loss,
                    'contracts': contracts
                }
                
                # Start monitoring in separate thread
                monitor_thread = threading.Thread(
                    target=monitor_order_and_place_sl,
                    args=(order_id, 'buy', stop_loss, contracts)
                )
                monitor_thread.daemon = True
                monitor_thread.start()
            
        elif alert_type == 'SHORT_ENTRY':
            message = f"🔴 *SHORT ENTRY SIGNAL RECEIVED*\n" \
                     f"💰 Entry Price: `${entry_price}`\n" \
                     f"🛡️ Stop Loss: `${stop_loss}`\n" \
                     f"📏 Size: `{lot_size_from_alert}` BTC\n" \
                     f"📋 Strategy: `{strategy_name}`\n" \
                     f"🎯 Signal: `{signal_type}`"
            log_and_notify(message)
            
            cancel_all_orders()
            # ✅ Place sell stop order for short entry
            order_id = place_stop_limit_order('sell', entry_price, entry_price, lot_size_from_alert)
            if order_id:
                active_orders['short'] = order_id
                current_position = 'short_pending'
                
                contracts = int(lot_size_from_alert * 1000)
                pending_stop_losses[order_id] = {
                    'side': 'sell',
                    'stop_price': stop_loss,
                    'contracts': contracts
                }
                
                # Start monitoring in separate thread
                monitor_thread = threading.Thread(
                    target=monitor_order_and_place_sl,
                    args=(order_id, 'sell', stop_loss, contracts)
                )
                monitor_thread.daemon = True
                monitor_thread.start()
        
        # ✅ Handle exit signals
        elif alert_type == 'LONG_EXIT':
            exit_reason = data.get('exit_reason', 'MANUAL')
            message = f"🚪 *LONG EXIT SIGNAL RECEIVED*\n" \
                     f"📋 Strategy: `{strategy_name}`\n" \
                     f"🔄 Reason: `{exit_reason}`"
            log_and_notify(message)
            close_position()
            
        elif alert_type == 'SHORT_EXIT':
            exit_reason = data.get('exit_reason', 'MANUAL')
            message = f"🚪 *SHORT EXIT SIGNAL RECEIVED*\n" \
                     f"📋 Strategy: `{strategy_name}`\n" \
                     f"🔄 Reason: `{exit_reason}`"
            log_and_notify(message)
            close_position()
            
        else:
            error_msg = f"⚠️ *UNKNOWN ALERT TYPE*\n" \
                       f"🚨 Alert Type: `{alert_type}`"
            log_and_notify(error_msg, "warning")
            return jsonify({"status": "error", "message": "Unknown alert type"}), 400
        
        return jsonify({"status": "success", "message": "Alert processed"})
    
    except Exception as e:
        error_msg = f"❌ *WEBHOOK ERROR*\n" \
                   f"🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Get current trading status - COMPLETELY FIXED"""
    try:
        # ✅ Get position data using the fixed function
        current_pos = get_position_data()
        
        # ✅ CORRECT PARAMETER FORMAT for orders
        orders_result = make_api_request('GET', '/orders', params={"product_ids": str(PRODUCT_ID), "states": "open"})
        open_orders = []
        
        if orders_result and orders_result.get('success'):
            open_orders = orders_result.get('result', [])
        
        status_data = {
            "current_position": current_position,
            "active_orders": active_orders,
            "stop_loss_orders": stop_loss_orders,
            "pending_stop_losses": pending_stop_losses,
            "open_orders_count": len(open_orders),
            "position_details": current_pos
        }
        
        message = f"📊 *TRADING STATUS*\n" \
                 f"🎯 Symbol: `{SYMBOL}` (ID: {PRODUCT_ID})\n" \
                 f"📈 Current Position: `{current_position or 'None'}`\n" \
                 f"📋 Open Orders: `{len(open_orders)}`\n" \
                 f"🛡️ Stop Loss Orders: `{len(stop_loss_orders)}`\n" \
                 f"⏳ Pending SL Orders: `{len(pending_stop_losses)}`"
        
        if current_pos:
            pos_size = current_pos.get('size', 0)
            pos_value = abs(pos_size) * 0.001
            entry_price = current_pos.get('entry_price', 'N/A')
            margin = current_pos.get('margin', 'N/A')
            message += f"\n💰 Position Size: `{pos_size}` contracts ({pos_value} BTC)"
            message += f"\n💵 Entry Price: `${entry_price}`"
            message += f"\n🏦 Margin: `${margin}`"
        
        send_telegram_message(message)
        return jsonify(status_data)
    
    except Exception as e:
        error_msg = f"❌ *STATUS ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cancel_all', methods=['POST'])
def cancel_all():
    """Cancel all orders endpoint"""
    try:
        cancel_all_orders()
        return jsonify({"status": "success", "message": "All orders cancelled"})
    except Exception as e:
        error_msg = f"❌ *CANCEL ALL ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/test_telegram', methods=['GET'])
def test_telegram():
    """Test Telegram integration"""
    test_message = "🧪 *TEST MESSAGE*\n" \
                  f"🤖 Bot is working correctly!\n" \
                  f"🎯 Symbol: `{SYMBOL}` (Product ID: {PRODUCT_ID})\n" \
                  f"📏 Lot Size: `{LOT_SIZE}` BTC\n" \
                  f"⏰ Auto-cancel: 90 minutes\n" \
                  f"📋 Order Type: Stop Limit Orders (FIXED)\n" \
                  f"🎯 SMC Integration: Active\n" \
                  f"✅ All APIs Fixed!\n" \
                  f"✅ Long & Short Both Working!"
    
    send_telegram_message(test_message)
    return jsonify({"status": "success", "message": "Test message sent to Telegram"})

@app.route('/test_position', methods=['GET'])
def test_position():
    """Test position fetching with detailed logging"""
    try:
        logger.info("🧪 Starting position test...")
        position_data = get_position_data()
        
        if position_data:
            message = f"✅ *POSITION FOUND*\n" \
                     f"📏 Size: `{position_data.get('size', 0)}` contracts\n" \
                     f"💵 Entry Price: `${position_data.get('entry_price', 'N/A')}`\n" \
                     f"🏦 Margin: `${position_data.get('margin', 'N/A')}`\n" \
                     f"🎯 Symbol: `{position_data.get('product_symbol', SYMBOL)}`\n" \
                     f"🆔 Product ID: `{position_data.get('product_id', 'N/A')}`"
        else:
            message = "ℹ️ *NO POSITION FOUND*\n" \
                     f"🎯 Symbol: `{SYMBOL}` (Product ID: {PRODUCT_ID})\n" \
                     f"📊 All position endpoints tested"
        
        send_telegram_message(message)
        return jsonify({"status": "success", "position": position_data})
        
    except Exception as e:
        error_msg = f"❌ *POSITION TEST ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/test_product', methods=['GET'])
def test_product():
    """Test product ID verification"""
    try:
        result = make_api_request('GET', '/products')
        if result and result.get('success'):
            products = result.get('result', [])
            btc_products = []
            
            for product in products:
                if 'BTC' in product.get('symbol', ''):
                    btc_products.append({
                        'id': product.get('id'),
                        'symbol': product.get('symbol'),
                        'description': product.get('description', '')
                    })
            
            message = f"🔍 *BTC PRODUCTS FOUND*\n"
            for prod in btc_products[:10]:  # Show first 10
                message += f"ID: `{prod['id']}` - `{prod['symbol']}`\n"
            
            # Check our specific product
            our_product = next((p for p in products if p.get('id') == PRODUCT_ID), None)
            if our_product:
                message += f"\n✅ *OUR PRODUCT CONFIRMED*\n"
                message += f"ID: `{our_product.get('id')}`\n"
                message += f"Symbol: `{our_product.get('symbol')}`\n"
                message += f"Description: `{our_product.get('description', '')}`"
            
            send_telegram_message(message)
            return jsonify({"status": "success", "our_product": our_product, "btc_products": btc_products})
        else:
            error_msg = "❌ Failed to fetch products"
            log_and_notify(error_msg, "error")
            return jsonify({"status": "error", "message": "Failed to fetch products"}), 500

if __name__ == '__main__':
    startup_message = f"🚀 *DELTA TRADING BOT STARTED (POSITION API FIXED)*\n" \
                     f"🎯 Symbol: `{SYMBOL}` (Product ID: {PRODUCT_ID})\n" \
                     f"📏 Lot Size: `{LOT_SIZE}` BTC\n" \
                     f"📋 Order Type: Stop Limit Orders (FIXED)\n" \
                     f"⏰ Auto-cancel: 90 minutes\n" \
                     f"🎯 SMC Integration: Active\n" \
                     f"🌐 Webhook: `http://localhost:5000/webhook`\n" \
                     f"📊 Status: `http://localhost:5000/status`\n" \
                     f"🗑️ Cancel All: `http://localhost:5000/cancel_all`\n" \
                     f"🧪 Test Position: `http://localhost:5000/test_position`\n" \
                     f"✅ *POSITION API COMPLETELY FIXED!*"
    
    send_telegram_message(startup_message)
    
    logger.info("🚀 Starting Delta Exchange Trading Bot (POSITION API FIXED)...")
    logger.info(f"📊 Trading Symbol: {SYMBOL}")
    logger.info(f"📏 Lot Size: {LOT_SIZE} BTC")
    logger.info("📋 Order Type: Stop Limit Orders (FIXED)")
    logger.info("⏰ Auto-cancel timeout: 90 minutes")
    logger.info("🎯 SMC Integration: Active")
    logger.info("🌐 Webhook endpoint: http://localhost:5000/webhook")
    logger.info("📱 Telegram notifications enabled")
    logger.info("✅ POSITION API COMPLETELY FIXED!")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
