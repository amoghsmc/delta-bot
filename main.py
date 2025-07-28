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
SYMBOL = 'BTCUSD'
PRODUCT_ID = 27
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
        
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        error_text = e.response.text
        status_code = e.response.status_code
        reason = e.response.reason
        error_msg = f"❌ API request failed: {status_code} {reason} | {error_text}"
    else:
        error_msg = f"❌ API request failed: {e}"
    log_and_notify(error_msg, "error")
    return None


def get_order_status(order_id):
    """Get order status by order ID"""
    result = make_api_request('GET', f'/orders/{order_id}')
    if result and result.get('success'):
        return result.get('result')
    return None

def place_stop_limit_order(side, stop_price, limit_price, size):
    """Place a stop-limit order (Buy/Sell Stop Limit)"""
    contracts = int(size * 1000)
    stop_side = side.lower()

    # Offset for gap between stop and limit
    gap = 50
    if stop_side == "buy":
        stop_order_type = "take_profit_order"
        limit_price = stop_price + gap  # BUY: limit price above stop
    else:
        stop_order_type = "stop_loss_order"
        limit_price = stop_price - gap  # SELL: limit price below stop

    order_data = {
        "product_symbol": SYMBOL,
        "size": contracts,
        "side": stop_side,
        "order_type": "limit_order",
        "limit_price": str(limit_price),
        "stop_order_type": stop_order_type,
        "stop_price": str(stop_price),
        "stop_trigger_method": "mark_price"
    }

    payload = json.dumps(order_data)
    result = make_api_request('POST', '/orders', payload)

    if result and result.get('success'):
        order_id = result['result']['id']
        message = f"🚀 *{side.upper()} STOP LIMIT ORDER PLACED*\n" \
                  f"🔼 Stop Price: `${stop_price}`\n" \
                  f"🎯 Limit Price: `${limit_price}`\n" \
                  f"📏 Size: `{contracts}` contracts ({size} BTC)\n" \
                  f"🎯 Symbol: `{SYMBOL}`\n" \
                  f"⏳ Will auto-cancel in 90 minutes if not filled..."
        log_and_notify(message)
        return order_id
    else:
        error_msg = f"❌ *FAILED TO PLACE {side.upper()} STOP LIMIT ORDER*\n" \
                    f"🔼 Stop Price: `${stop_price}`\n" \
                    f"🎯 Limit Price: `${limit_price}`\n" \
                    f"🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")
        return None

def monitor_order_and_place_sl(order_id, original_side, stop_loss_price, contracts):
    """Monitor order fill status and wait for PineScript to trigger SL"""
    max_attempts = 5400  # 90 minutes with 1-second intervals
    attempt = 0

    message = f"👀 *MONITORING ORDER FILL*\n" \
             f"📊 Order ID: `{order_id}`\n" \
             f"⏱️ Auto-cancel in 90 minutes if not filled\n" \
             f"🔍 Checking every second for fill status..."
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
                             f"🛡️ SL will now be triggered by PineScript alert"
                    log_and_notify(message)

                    # Remove from pending
                    if order_id in pending_stop_losses:
                        del pending_stop_losses[order_id]
                    break

                elif state in ['cancelled', 'rejected']:
                    message = f"❌ *ORDER {state.upper()}*\n" \
                             f"📊 Order ID: `{order_id}`\n" \
                             f"🚫 SL will not be placed"
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
                 f"⚠️ Not filled within 90 minutes\n" \
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
    """Cancel all open orders for the symbol"""
    params = {"product_id": PRODUCT_ID, "state": "open"}
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
            else:
                logger.error(f"❌ Failed to cancel order: {order_id}")
        
        if cancelled_count > 0:
            message = f"🗑️ *ORDERS CANCELLED*\n" \
                     f"📊 Cancelled: `{cancelled_count}` orders\n" \
                     f"🎯 Symbol: `{SYMBOL}`"
            log_and_notify(message)
        
        # Clear pending stop losses for cancelled orders
        global pending_stop_losses
        pending_stop_losses.clear()

def close_position():
    """Close current position with market order"""
    global current_position
    
    if not current_position:
        return
    
    result = make_api_request('GET', '/positions')
    if not result or not result.get('success'):
        log_and_notify("❌ Failed to get positions", "error")
        return
    
    positions = result.get('result', [])
    btc_position = None
    
    for pos in positions:
        if pos.get('product_symbol') == SYMBOL:
            btc_position = pos
            break
    
    if not btc_position or btc_position.get('size') == 0:
        message = "ℹ️ *NO POSITION TO CLOSE*\n" \
                 f"🎯 Symbol: `{SYMBOL}`"
        log_and_notify(message)
        current_position = None
        return
    
    position_size = abs(int(btc_position['size']))
    close_side = "sell" if btc_position['size'] > 0 else "buy"
    position_value = position_size * 0.001
    
    close_order_data = {
        "product_symbol": SYMBOL,
        "size": position_size,
        "side": close_side,
        "order_type": "market_order",
        "reduce_only": "true"
    }
    
    payload = json.dumps(close_order_data)
    result = make_api_request('POST', '/orders', payload)
    
    if result and result.get('success'):
        message = f"🚪 *POSITION CLOSED*\n" \
                 f"📊 Order ID: `{result['result']['id']}`\n" \
                 f"📏 Size: `{position_size}` contracts ({position_value} BTC)\n" \
                 f"🔄 Side: `{close_side.upper()}`\n" \
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
    """Handle TradingView webhook alerts"""
    global current_position, active_orders, pending_stop_losses
    
    try:
        data = request.get_json()
        logger.info(f"📨 Received alert: {data}")
        
        alert_type = data.get('alert_type')
        entry_price = float(data.get('entry_price', 0))
        stop_loss = float(data.get('stop_loss', 0))
        
        # ✅ NEW: Extract additional data from SMC indicator
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
                     f"🎯 Signal: `{signal_type}`\n" \
                     f"📋 Order Type: {entry_method}"
            log_and_notify(message)
            
            cancel_all_orders()
            # Use dynamic lot size from alert
            order_id = place_stop_limit_order('buy', entry_price, entry_price, lot_size_from_alert)
            if order_id:
                active_orders['long'] = order_id
                current_position = 'long_pending'
                
                # Use dynamic lot size
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
                     f"🎯 Signal: `{signal_type}`\n" \
                     f"📋 Order Type: {entry_method}"
            log_and_notify(message)
            
            cancel_all_orders()
            # Use dynamic lot size from alert
            order_id = place_stop_limit_order('sell', entry_price, entry_price, lot_size_from_alert)
            if order_id:
                active_orders['short'] = order_id
                current_position = 'short_pending'
                
                # Use dynamic lot size
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
        
        # ✅ NEW: Handle exit signals from SMC indicator
        elif alert_type == 'LONG_EXIT':
            exit_reason = data.get('exit_reason', 'MANUAL')
            message = f"🚪 *LONG EXIT SIGNAL RECEIVED*\n" \
                     f"📋 Strategy: `{strategy_name}`\n" \
                     f"🔄 Reason: `{exit_reason}`\n" \
                     f"🔄 Closing long position..."
            log_and_notify(message)
            close_position()
            
        elif alert_type == 'SHORT_EXIT':
            exit_reason = data.get('exit_reason', 'MANUAL')
            message = f"🚪 *SHORT EXIT SIGNAL RECEIVED*\n" \
                     f"📋 Strategy: `{strategy_name}`\n" \
                     f"🔄 Reason: `{exit_reason}`\n" \
                     f"🔄 Closing short position..."
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
    """Get current trading status"""
    try:
        positions_result = make_api_request('GET', '/positions')
        current_pos = None
        
        if positions_result and positions_result.get('success'):
            positions = positions_result.get('result', [])
            for pos in positions:
                if pos.get('product_symbol') == SYMBOL and pos.get('size') != 0:
                    current_pos = pos
                    break
        
        orders_result = make_api_request('GET', '/orders', params={"product_id": PRODUCT_ID, "state": "open"})
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
                 f"🎯 Symbol: `{SYMBOL}`\n" \
                 f"📈 Current Position: `{current_position or 'None'}`\n" \
                 f"📋 Open Orders: `{len(open_orders)}`\n" \
                 f"🛡️ Stop Loss Orders: `{len(stop_loss_orders)}`\n" \
                 f"⏳ Pending SL Orders: `{len(pending_stop_losses)}`\n" \
                 f"⏰ Auto-cancel: 90 minutes"
        
        if current_pos:
            pos_size = current_pos.get('size', 0)
            pos_value = abs(pos_size) * 0.001
            message += f"\n💰 Position Size: `{pos_size}` contracts ({pos_value} BTC)"
        
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
                  f"🎯 Symbol: `{SYMBOL}`\n" \
                  f"📏 Lot Size: `{LOT_SIZE}` BTC\n" \
                  f"⏰ Auto-cancel: 90 minutes\n" \
                  f"📋 Order Type: Stop Limit Orders\n" \
                  f"🎯 SMC Integration: Active"
    
    send_telegram_message(test_message)
    return jsonify({"status": "success", "message": "Test message sent to Telegram"})

if __name__ == '__main__':
    startup_message = f"🚀 *DELTA TRADING BOT STARTED*\n" \
                     f"🎯 Symbol: `{SYMBOL}`\n" \
                     f"📏 Lot Size: `{LOT_SIZE}` BTC\n" \
                     f"📋 Order Type: Stop Limit Orders\n" \
                     f"⏰ Auto-cancel: 90 minutes\n" \
                     f"🎯 SMC Integration: Active\n" \
                     f"🌐 Webhook: `http://localhost:5000/webhook`\n" \
                     f"📊 Status: `http://localhost:5000/status`\n" \
                     f"🗑️ Cancel All: `http://localhost:5000/cancel_all`\n" \
                     f"✨ *NEW: AMOGH SMC Strategy Integration*"
    
    send_telegram_message(startup_message)
    
    logger.info("🚀 Starting Delta Exchange Trading Bot...")
    logger.info(f"📊 Trading Symbol: {SYMBOL}")
    logger.info(f"📏 Lot Size: {LOT_SIZE} BTC")
    logger.info("📋 Order Type: Stop Limit Orders")
    logger.info("⏰ Auto-cancel timeout: 90 minutes")
    logger.info("🎯 SMC Integration: Active")
    logger.info("🌐 Webhook endpoint: http://localhost:5000/webhook")
    logger.info("📱 Telegram notifications enabled")
    logger.info("✨ AMOGH SMC Strategy Integration Ready")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
            
