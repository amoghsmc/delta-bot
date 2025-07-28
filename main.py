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
API_KEY = 'NWczUdbI9vVbBlCASC0rRFolMpPM32'  # Replace with your actual API key
API_SECRET = 'YTN79e7x2vuLSYzGW7YUBMnZNJEXTDPxsMaEpH0ZwXptQRwl9zjEby0Z8oAp'  # Replace with your actual API secret

# Telegram Configuration
TELEGRAM_BOT_TOKEN = '8068558939:AAHcsThdbt0J1uzI0mT140H9vJXbcaVZ9Jk'  # Replace with your actual bot token
TELEGRAM_CHAT_ID = '871704959'  # Replace with your actual chat ID
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

# Trading Configuration
SYMBOL = 'BTCUSD'  # This is correct for BTCUSD.P
PRODUCT_ID = 27    # BTCUSD.P perpetual futures
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
        
        # ✅ Method 1: Use /positions/margined (most reliable - no required params)
        result = make_api_request('GET', '/positions/margined')
        
        if result and result.get('success'):
            positions = result.get('result', [])
            logger.info(f"✅ Got {len(positions)} positions from /positions/margined")
            
            for pos in positions:
                logger.info(f"🔍 Position: {pos.get('product_symbol', 'N/A')} | Size: {pos.get('size', 0)} | ID: {pos.get('product_id', 'N/A')}")
                # Check both symbol and product_id for exact match
                if (pos.get('product_symbol') == SYMBOL or pos.get('product_id') == PRODUCT_ID) and pos.get('size') != 0:
                    logger.info(f"✅ Found matching position: {pos}")
                    return pos
        
        # ✅ Method 2: Use /positions with REQUIRED product_id parameter
        logger.info(f"🔍 Trying /positions with product_id={PRODUCT_ID}...")
        params = {"product_id": PRODUCT_ID}  # This is REQUIRED
        result = make_api_request('GET', '/positions', params=params)
        
        if result and result.get('success'):
            position_data = result.get('result')
            logger.info(f"✅ Got position data: {position_data}")
            if position_data and position_data.get('size') != 0:
                return position_data
        
        logger.info("ℹ️ No open position found")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error getting position data: {e}")
        return None

def place_entry_order(side, entry_price, size):
    """Place entry order - COMPLETELY FIXED FOR DELTA EXCHANGE"""
    contracts = int(size * 1000)
    
    # ✅ FOR ENTRY ORDERS - USE SIMPLE LIMIT ORDERS, NOT STOP ORDERS
    order_data = {
        "product_id": PRODUCT_ID,
        "size": contracts,
        "side": side.lower(),
        "order_type": "limit_order",
        "limit_price": str(entry_price)
    }
    
    logger.info(f"✅ Entry Order Data: {order_data}")
    payload = json.dumps(order_data)
    result = make_api_request('POST', '/orders', payload)

    if result and result.get('success'):
        order_id = result['result']['id']
        message = f"🚀 *{side.upper()} ENTRY ORDER PLACED*\n" \
                  f"💰 Entry Price: `${entry_price}`\n" \
                  f"📏 Size: `{contracts}` contracts ({size} BTC)\n" \
                  f"🎯 Symbol: `{SYMBOL}`\n" \
                  f"📋 Order ID: `{order_id}`"
        log_and_notify(message)
        return order_id
    else:
        error_msg = f"❌ *FAILED TO PLACE {side.upper()} ENTRY ORDER*\n" \
                    f"💰 Entry Price: `${entry_price}`\n" \
                    f"🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")
        return None

def place_stop_loss_order(position_side, stop_price, size):
    """Place stop loss order for existing position"""
    contracts = int(size * 1000)
    
    # ✅ STOP LOSS LOGIC
    if position_side > 0:  # Long position
        sl_side = "sell"
        stop_order_type = "stop_loss_order"
    else:  # Short position
        sl_side = "buy"
        stop_order_type = "stop_loss_order"
    
    # ✅ STOP LOSS ORDER DATA
    order_data = {
        "product_id": PRODUCT_ID,
        "size": contracts,
        "side": sl_side,
        "order_type": "market_order",  # Market order for SL
        "stop_order_type": stop_order_type,
        "stop_price": str(stop_price),
        "stop_trigger_method": "mark_price",
        "reduce_only": "true"  # Only close position
    }
    
    logger.info(f"✅ Stop Loss Order Data: {order_data}")
    payload = json.dumps(order_data)
    result = make_api_request('POST', '/orders', payload)

    if result and result.get('success'):
        order_id = result['result']['id']
        message = f"🛡️ *STOP LOSS ORDER PLACED*\n" \
                  f"🔻 Stop Price: `${stop_price}`\n" \
                  f"📏 Size: `{contracts}` contracts\n" \
                  f"🔄 Side: `{sl_side.upper()}`\n" \
                  f"📋 Order ID: `{order_id}`"
        log_and_notify(message)
        return order_id
    else:
        error_msg = f"❌ *FAILED TO PLACE STOP LOSS*\n" \
                    f"🔻 Stop Price: `${stop_price}`\n" \
                    f"🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")
        return None

def monitor_order_and_place_sl(order_id, original_side, stop_loss_price, contracts):
    """Monitor order fill and place SL"""
    max_attempts = 5400  # 90 minutes
    attempt = 0

    message = f"👀 *MONITORING ORDER FILL*\n" \
             f"📊 Order ID: `{order_id}`\n" \
             f"⏱️ Will auto-cancel in 90 minutes if not filled"
    log_and_notify(message)

    while attempt < max_attempts:
        try:
            order_status = get_order_status(order_id)

            if order_status:
                state = order_status.get('state')
                filled_size = order_status.get('size_filled', 0)

                logger.info(f"Order {order_id} - State: {state}, Filled: {filled_size}")

                if state == 'filled':
                    message = f"✅ *ORDER FILLED - PLACING STOP LOSS*\n" \
                             f"📊 Order ID: `{order_id}`\n" \
                             f"📏 Filled Size: `{filled_size}` contracts"
                    log_and_notify(message)

                    # ✅ Now place stop loss
                    position_data = get_position_data()
                    if position_data:
                        position_size = position_data.get('size', 0)
                        sl_order_id = place_stop_loss_order(position_size, stop_loss_price, abs(position_size) * 0.001)
                        if sl_order_id:
                            stop_loss_orders[order_id] = sl_order_id

                    # Remove from pending
                    if order_id in pending_stop_losses:
                        del pending_stop_losses[order_id]
                    break

                elif state in ['cancelled', 'rejected']:
                    message = f"❌ *ORDER {state.upper()}*\n" \
                             f"📊 Order ID: `{order_id}`"
                    log_and_notify(message, "warning")

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

    # Auto-cancel if timeout
    if attempt >= max_attempts:
        message = f"⏰ *90 MINUTE TIMEOUT - CANCELLING ORDER*\n" \
                 f"📊 Order ID: `{order_id}`"
        log_and_notify(message, "warning")

        cancel_result = make_api_request('DELETE', f'/orders/{order_id}')
        if cancel_result and cancel_result.get('success'):
            log_and_notify(f"✅ *ORDER AUTO-CANCELLED*\n📊 Order ID: `{order_id}`")

        if order_id in pending_stop_losses:
            del pending_stop_losses[order_id]

def cancel_all_orders():
    """Cancel all open orders"""
    try:
        params = {"product_ids": str(PRODUCT_ID), "states": "open"}
        result = make_api_request('GET', '/orders', params=params)
        
        if result and result.get('success'):
            orders = result.get('result', [])
            cancelled_count = 0
            
            for order in orders:
                order_id = order['id']
                cancel_result = make_api_request('DELETE', f'/orders/{order_id}')
                if cancel_result and cancel_result.get('success'):
                    cancelled_count += 1
                    logger.info(f"✅ Cancelled order: {order_id}")
            
            if cancelled_count > 0:
                message = f"🗑️ *{cancelled_count} ORDERS CANCELLED*"
                log_and_notify(message)
            
            global pending_stop_losses, stop_loss_orders
            pending_stop_losses.clear()
            stop_loss_orders.clear()
            
    except Exception as e:
        logger.error(f"❌ Error cancelling orders: {e}")

def close_position():
    """Close current position"""
    global current_position
    
    position_data = get_position_data()
    
    if not position_data or position_data.get('size') == 0:
        message = "ℹ️ *NO POSITION TO CLOSE*"
        log_and_notify(message)
        current_position = None
        return
    
    position_size = abs(int(position_data['size']))
    close_side = "sell" if position_data['size'] > 0 else "buy"
    
    close_order_data = {
        "product_id": PRODUCT_ID,
        "size": position_size,
        "side": close_side,
        "order_type": "market_order",
        "reduce_only": "true"
    }
    
    payload = json.dumps(close_order_data)
    result = make_api_request('POST', '/orders', payload)
    
    if result and result.get('success'):
        message = f"🚪 *POSITION CLOSED*\n" \
                 f"📏 Size: `{position_size}` contracts\n" \
                 f"🔄 Side: `{close_side.upper()}`"
        log_and_notify(message)
        current_position = None
        cancel_all_orders()
    else:
        error_msg = f"❌ *FAILED TO CLOSE POSITION*\n🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle TradingView webhook alerts"""
    global current_position, active_orders, pending_stop_losses
    
    try:
        data = request.get_json()
        logger.info(f"📨 Received alert: {data}")
        
        alert_type = data.get('alert_type')
        entry_price = float(data.get('entry_price', 0))
        stop_loss = float(data.get('stop_loss', 0))
        lot_size_from_alert = float(data.get('lot_size', LOT_SIZE))
        
        if alert_type == 'LONG_ENTRY':
            message = f"🟢 *LONG ENTRY SIGNAL*\n" \
                     f"💰 Entry: `${entry_price}`\n" \
                     f"🛡️ Stop Loss: `${stop_loss}`\n" \
                     f"📏 Size: `{lot_size_from_alert}` BTC"
            log_and_notify(message)
            
            cancel_all_orders()
            # ✅ Place simple limit order for long entry
            order_id = place_entry_order('buy', entry_price, lot_size_from_alert)
            if order_id:
                active_orders['long'] = order_id
                current_position = 'long_pending'
                
                contracts = int(lot_size_from_alert * 1000)
                pending_stop_losses[order_id] = {
                    'side': 'buy',
                    'stop_price': stop_loss,
                    'contracts': contracts
                }
                
                monitor_thread = threading.Thread(
                    target=monitor_order_and_place_sl,
                    args=(order_id, 'buy', stop_loss, contracts)
                )
                monitor_thread.daemon = True
                monitor_thread.start()
            
        elif alert_type == 'SHORT_ENTRY':
            message = f"🔴 *SHORT ENTRY SIGNAL*\n" \
                     f"💰 Entry: `${entry_price}`\n" \
                     f"🛡️ Stop Loss: `${stop_loss}`\n" \
                     f"📏 Size: `{lot_size_from_alert}` BTC"
            log_and_notify(message)
            
            cancel_all_orders()
            # ✅ Place simple limit order for short entry
            order_id = place_entry_order('sell', entry_price, lot_size_from_alert)
            if order_id:
                active_orders['short'] = order_id
                current_position = 'short_pending'
                
                contracts = int(lot_size_from_alert * 1000)
                pending_stop_losses[order_id] = {
                    'side': 'sell',
                    'stop_price': stop_loss,
                    'contracts': contracts
                }
                
                monitor_thread = threading.Thread(
                    target=monitor_order_and_place_sl,
                    args=(order_id, 'sell', stop_loss, contracts)
                )
                monitor_thread.daemon = True
                monitor_thread.start()
        
        elif alert_type in ['LONG_EXIT', 'SHORT_EXIT']:
            message = f"🚪 *{alert_type.replace('_', ' ')} SIGNAL*"
            log_and_notify(message)
            close_position()
            
        else:
            error_msg = f"⚠️ *UNKNOWN ALERT TYPE: {alert_type}*"
            log_and_notify(error_msg, "warning")
            return jsonify({"status": "error", "message": "Unknown alert type"}), 400
        
        return jsonify({"status": "success", "message": "Alert processed"})
    
    except Exception as e:
        error_msg = f"❌ *WEBHOOK ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Get current trading status"""
    try:
        current_pos = get_position_data()
        
        orders_result = make_api_request('GET', '/orders', params={"product_ids": str(PRODUCT_ID), "states": "open"})
        open_orders = []
        
        if orders_result and orders_result.get('success'):
            open_orders = orders_result.get('result', [])
        
        message = f"📊 *TRADING STATUS*\n" \
                 f"🎯 Symbol: `{SYMBOL}` (ID: {PRODUCT_ID})\n" \
                 f"📈 Position: `{current_position or 'None'}`\n" \
                 f"📋 Open Orders: `{len(open_orders)}`\n" \
                 f"🛡️ Stop Loss Orders: `{len(stop_loss_orders)}`\n" \
                 f"⏳ Pending SL Orders: `{len(pending_stop_losses)}`"
        
        if current_pos:
            pos_size = current_pos.get('size', 0)
            entry_price = current_pos.get('entry_price', 'N/A')
            margin = current_pos.get('margin', 'N/A')
            message += f"\n💰 Position: `{pos_size}` contracts\n💵 Entry: `${entry_price}`\n🏦 Margin: `${margin}`"
        
        send_telegram_message(message)
        return jsonify({"status": "success", "position": current_pos, "orders": len(open_orders)})
    
    except Exception as e:
        error_msg = f"❌ *STATUS ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cancel_all', methods=['POST'])
def cancel_all():
    """Cancel all orders"""
    try:
        cancel_all_orders()
        return jsonify({"status": "success", "message": "All orders cancelled"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/test_telegram', methods=['GET'])
def test_telegram():
    """Test Telegram"""
    test_message = "🧪 *TEST MESSAGE*\n" \
                  f"🤖 Bot working!\n" \
                  f"🎯 Symbol: `{SYMBOL}` (ID: {PRODUCT_ID})\n" \
                  f"✅ Entry Orders: Simple Limit Orders\n" \
                  f"✅ Stop Loss: After Fill\n" \
                  f"✅ Position API: Fixed\n" \
                  f"✅ Long & Short: Both Fixed!"
    
    send_telegram_message(test_message)
    return jsonify({"status": "success", "message": "Test sent"})

@app.route('/debug_position', methods=['GET'])
def debug_position():
    """Debug position API calls"""
    try:
        debug_info = []
        
        # Test Method 1: /positions/margined
        logger.info("🧪 Testing /positions/margined...")
        result1 = make_api_request('GET', '/positions/margined')
        debug_info.append({
            "method": "/positions/margined",
            "success": result1.get('success') if result1 else False,
            "result": result1
        })
        
        # Test Method 2: /positions with product_id
        logger.info(f"🧪 Testing /positions with product_id={PRODUCT_ID}...")
        params = {"product_id": PRODUCT_ID}
        result2 = make_api_request('GET', '/positions', params=params)
        debug_info.append({
            "method": f"/positions?product_id={PRODUCT_ID}",
            "success": result2.get('success') if result2 else False,
            "result": result2
        })
        
        # Test Method 3: /positions with underlying_asset_symbol
        logger.info("🧪 Testing /positions with underlying_asset_symbol=BTC...")
        params = {"underlying_asset_symbol": "BTC"}
        result3 = make_api_request('GET', '/positions', params=params)
        debug_info.append({
            "method": "/positions?underlying_asset_symbol=BTC",
            "success": result3.get('success') if result3 else False,
            "result": result3
        })
        
        # Send summary to Telegram
        message = f"🧪 *POSITION API DEBUG*\n"
        for i, info in enumerate(debug_info, 1):
            status = "✅" if info['success'] else "❌"
            message += f"{status} Method {i}: {info['method']}\n"
        
        # Show position details if found
        current_pos = get_position_data()
        if current_pos:
            message += f"\n✅ *POSITION FOUND*\n"
            message += f"📏 Size: `{current_pos.get('size', 0)}`\n"
            message += f"💵 Entry: `${current_pos.get('entry_price', 'N/A')}`\n"
            message += f"🎯 Symbol: `{current_pos.get('product_symbol', 'N/A')}`"
        else:
            message += f"\nℹ️ *NO POSITION FOUND*"
        
        send_telegram_message(message)
        
        return jsonify({
            "status": "success",
            "debug_info": debug_info,
            "product_id": PRODUCT_ID,
            "symbol": SYMBOL,
            "current_position": current_pos
        })
        
    except Exception as e:
        error_msg = f"❌ *DEBUG ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

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

if __name__ == '__main__':
    startup_message = f"🚀 *DELTA BOT STARTED (COMPLETELY FIXED)*\n" \
                     f"🎯 Symbol: `{SYMBOL}` (ID: {PRODUCT_ID})\n" \
                     f"📏 Lot Size: `{LOT_SIZE}` BTC\n" \
                     f"✅ Entry: Simple Limit Orders\n" \
                     f"✅ Stop Loss: After Position Fill\n" \
                     f"✅ Position API: Fixed\n" \
                     f"✅ Long & Short: Both Working\n" \
                     f"🌐 Webhook: `http://localhost:5000/webhook`\n" \
                     f"🧪 Debug: `http://localhost:5000/debug_position`"
    
    send_telegram_message(startup_message)
    
    logger.info("🚀 Starting Delta Exchange Trading Bot (COMPLETELY FIXED)...")
    logger.info(f"📊 Trading Symbol: {SYMBOL} (Product ID: {PRODUCT_ID})")
    logger.info("✅ Entry Orders: Simple Limit Orders (No Stop Orders for Entry)")
    logger.info("✅ Stop Loss: Placed after position is filled")
    logger.info("✅ Position API: Fixed with proper parameters")
    logger.info("✅ Long & Short: Both working correctly")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
