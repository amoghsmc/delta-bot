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

def verify_product():
    """Verify product details"""
    try:
        result = make_api_request('GET', f'/products/{PRODUCT_ID}')
        if result and result.get('success'):
            product = result['result']
            logger.info(f"✅ Product verified: {product.get('symbol')} | Status: {product.get('trading_status')}")
            return product
        else:
            logger.error(f"❌ Product {PRODUCT_ID} not found or inactive")
            return None
    except Exception as e:
        logger.error(f"❌ Product verification error: {e}")
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
    """Place entry order with enhanced error handling - FIXED VERSION"""
    try:
        # ✅ Verify product first
        product = verify_product()
        if not product:
            error_msg = f"❌ Product verification failed for {SYMBOL}"
            log_and_notify(error_msg, "error")
            return None
            
        # ✅ Calculate contracts properly
        contracts = max(1, int(size * 1000))  # Minimum 1 contract
        formatted_price = f"{float(entry_price):.2f}"
        
        # ✅ Get current market price for validation
        current_price = get_current_price()
        if current_price:
            logger.info(f"🔍 Current price: ${current_price}, Entry price: ${formatted_price}")
            
            # ✅ Validate order logic for your strategy
            if side.lower() == 'buy' and float(formatted_price) >= current_price:
                logger.info(f"ℹ️ Buy limit order at ${formatted_price} is above current price ${current_price} - will wait for price to come down")
            elif side.lower() == 'sell' and float(formatted_price) <= current_price:
                logger.info(f"ℹ️ Sell limit order at ${formatted_price} is below current price ${current_price} - will wait for price to come up")
        
        # ✅ PERFECT ORDER DATA FOR YOUR STRATEGY
        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "limit_order",  # ✅ Limit order as per your strategy
            "limit_price": formatted_price,
            "time_in_force": "gtc"  # Good till cancelled
        }
        
        logger.info(f"✅ Placing order: {order_data}")
        payload = json.dumps(order_data)
        result = make_api_request('POST', '/orders', payload)

        if result and result.get('success'):
            order_id = result['result']['id']
            order_state = result['result'].get('state', 'unknown')
            unfilled_size = result['result'].get('unfilled_size', contracts)
            
            message = f"🚀 *{side.upper()} LIMIT ORDER PLACED*\n" \
                      f"💰 Entry Price: `${formatted_price}`\n" \
                      f"📊 Current Price: `${current_price or 'N/A'}`\n" \
                      f"📏 Size: `{contracts}` contracts ({size} BTC)\n" \
                      f"🎯 Symbol: `{SYMBOL}`\n" \
                      f"📋 Order ID: `{order_id}`\n" \
                      f"📊 State: `{order_state}`\n" \
                      f"📈 Unfilled: `{unfilled_size}` contracts\n" \
                      f"⏰ Auto-cancel in 90 minutes if not filled"
            log_and_notify(message)
            return order_id
        else:
            # ✅ Detailed error logging
            error_code = result.get('error', {}).get('code', 'unknown') if result else 'no_response'
            error_context = result.get('error', {}).get('context', {}) if result else {}
            error_msg = f"❌ *FAILED TO PLACE {side.upper()} ORDER*\n" \
                        f"💰 Entry Price: `${formatted_price}`\n" \
                        f"📏 Size: `{contracts}` contracts\n" \
                        f"🚨 Error Code: `{error_code}`\n" \
                        f"🚨 Context: `{error_context}`\n" \
                        f"🚨 Full Response: `{result}`"
            log_and_notify(error_msg, "error")
            return None
            
    except Exception as e:
        error_msg = f"❌ *ORDER PLACEMENT EXCEPTION*\n" \
                    f"🚨 Error: `{str(e)}`\n" \
                    f"💰 Entry Price: `{entry_price}`\n" \
                    f"📏 Size: `{size}` BTC"
        log_and_notify(error_msg, "error")
        return None

def place_stop_loss_order(position_side, stop_price, size):
    """Place stop loss order for existing position - IMPROVED VERSION"""
    try:
        contracts = max(1, int(size * 1000))
        formatted_stop_price = f"{float(stop_price):.2f}"
        
        # ✅ STOP LOSS LOGIC - OPPOSITE OF POSITION
        if position_side > 0:  # Long position
            sl_side = "sell"
            stop_order_type = "stop_loss_order"  # Price goes DOWN
        else:  # Short position
            sl_side = "buy"
            stop_order_type = "stop_loss_order"  # Price goes UP (for short, SL is above entry)
        
        # ✅ IMPROVED STOP LOSS ORDER DATA
        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": sl_side,
            "order_type": "market_order",  # Execute immediately when triggered
            "stop_order_type": stop_order_type,
            "stop_price": formatted_stop_price,
            "stop_trigger_method": "mark_price",  # Use mark price for better execution
            "reduce_only": "true",  # ✅ Only close position
            "time_in_force": "gtc"  # Good till cancelled
        }
        
        logger.info(f"✅ Stop Loss Order Data: {order_data}")
        payload = json.dumps(order_data)
        result = make_api_request('POST', '/orders', payload)

        if result and result.get('success'):
            order_id = result['result']['id']
            order_state = result['result'].get('state', 'unknown')
            
            message = f"🛡️ *STOP LOSS ORDER PLACED*\n" \
                      f"🔻 Stop Price: `${formatted_stop_price}`\n" \
                      f"📏 Size: `{contracts}` contracts\n" \
                      f"🔄 Side: `{sl_side.upper()}`\n" \
                      f"📋 Order ID: `{order_id}`\n" \
                      f"📊 State: `{order_state}`\n" \
                      f"⚡ Will trigger if price hits `${formatted_stop_price}`"
            log_and_notify(message)
            return order_id
        else:
            error_code = result.get('error', {}).get('code', 'unknown') if result else 'no_response'
            error_msg = f"❌ *FAILED TO PLACE STOP LOSS*\n" \
                        f"🔻 Stop Price: `${formatted_stop_price}`\n" \
                        f"🚨 Error Code: `{error_code}`\n" \
                        f"🚨 Full Response: `{result}`"
            log_and_notify(error_msg, "error")
            return None
            
    except Exception as e:
        error_msg = f"❌ *STOP LOSS PLACEMENT EXCEPTION*\n" \
                    f"🚨 Error: `{str(e)}`\n" \
                    f"🔻 Stop Price: `{stop_price}`"
        log_and_notify(error_msg, "error")
        return None

def monitor_order_and_place_sl(order_id, original_side, stop_loss_price, contracts):
    """Monitor order fill and place SL - ENHANCED VERSION"""
    max_attempts = 5400  # 90 minutes (5400 seconds)
    attempt = 0

    message = f"👀 *MONITORING ORDER FILL*\n" \
             f"📊 Order ID: `{order_id}`\n" \
             f"🔄 Side: `{original_side.upper()}`\n" \
             f"🛡️ SL Price: `${stop_loss_price}`\n" \
             f"⏱️ Will auto-cancel in 90 minutes if not filled"
    log_and_notify(message)

    while attempt < max_attempts:
        try:
            order_status = get_order_status(order_id)

            if order_status:
                state = order_status.get('state')
                filled_size = order_status.get('size_filled', 0)
                unfilled_size = order_status.get('unfilled_size', 0)

                logger.info(f"Order {order_id} - State: {state}, Filled: {filled_size}, Unfilled: {unfilled_size}")

                if state == 'filled':
                    message = f"✅ *ORDER COMPLETELY FILLED*\n" \
                             f"📊 Order ID: `{order_id}`\n" \
                             f"📏 Filled Size: `{filled_size}` contracts\n" \
                             f"🛡️ Now placing Stop Loss..."
                    log_and_notify(message)

                    # ✅ Wait a moment for position to update
                    time.sleep(2)
                    
                    # ✅ Get updated position data
                    position_data = get_position_data()
                    if position_data:
                        position_size = position_data.get('size', 0)
                        position_size_btc = abs(position_size) * 0.001  # Convert to BTC
                        
                        sl_order_id = place_stop_loss_order(position_size, stop_loss_price, position_size_btc)
                        if sl_order_id:
                            stop_loss_orders[order_id] = sl_order_id
                            message = f"✅ *STOP LOSS SUCCESSFULLY PLACED*\n" \
                                     f"📊 Entry Order: `{order_id}`\n" \
                                     f"🛡️ SL Order: `{sl_order_id}`\n" \
                                     f"📏 Position: `{position_size}` contracts"
                            log_and_notify(message)
                    else:
                        error_msg = f"❌ *POSITION NOT FOUND AFTER FILL*\n" \
                                   f"📊 Order ID: `{order_id}`"
                        log_and_notify(error_msg, "error")

                    # Remove from pending
                    if order_id in pending_stop_losses:
                        del pending_stop_losses[order_id]
                    break

                elif state in ['cancelled', 'rejected']:
                    message = f"❌ *ORDER {state.upper()}*\n" \
                             f"📊 Order ID: `{order_id}`\n" \
                             f"📏 Filled: `{filled_size}` contracts"
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
                                 f"📈 Remaining: `{unfilled_size}` contracts\n" \
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
        else:
            log_and_notify(f"❌ *FAILED TO AUTO-CANCEL ORDER*\n📊 Order ID: `{order_id}`", "error")

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
                else:
                    logger.error(f"❌ Failed to cancel order: {order_id}")
            
            if cancelled_count > 0:
                message = f"🗑️ *{cancelled_count} ORDERS CANCELLED*"
                log_and_notify(message)
            else:
                logger.info("ℹ️ No orders to cancel")
            
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
                 f"🔄 Side: `{close_side.upper()}`\n" \
                 f"💰 Entry Price: `${position_data.get('entry_price', 'N/A')}`"
        log_and_notify(message)
        current_position = None
        cancel_all_orders()
    else:
        error_msg = f"❌ *FAILED TO CLOSE POSITION*\n🚨 Error: `{result}`"
        log_and_notify(error_msg, "error")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle TradingView webhook alerts - ENHANCED VERSION"""
    global current_position, active_orders, pending_stop_losses
    
    try:
        data = request.get_json()
        logger.info(f"📨 Received alert: {data}")
        
        alert_type = data.get('alert_type')
        entry_price = float(data.get('entry_price', 0))
        stop_loss = float(data.get('stop_loss', 0))
        lot_size_from_alert = float(data.get('lot_size', LOT_SIZE))
        
        # ✅ Get current price for context
        current_price = get_current_price()
        
        if alert_type == 'LONG_ENTRY':
            message = f"🟢 *LONG ENTRY SIGNAL RECEIVED*\n" \
                     f"📊 Current Price: `${current_price or 'N/A'}`\n" \
                     f"💰 Entry Price: `${entry_price}`\n" \
                     f"🛡️ Stop Loss: `${stop_loss}`\n" \
                     f"📏 Size: `{lot_size_from_alert}` BTC\n" \
                     f"📈 Strategy: Limit order will execute when price comes to `${entry_price}`"
            log_and_notify(message)
            
            cancel_all_orders()
            # ✅ Place limit order for long entry (your strategy)
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
            message = f"🔴 *SHORT ENTRY SIGNAL RECEIVED*\n" \
                     f"📊 Current Price: `${current_price or 'N/A'}`\n" \
                     f"💰 Entry Price: `${entry_price}`\n" \
                     f"🛡️ Stop Loss: `${stop_loss}`\n" \
                     f"📏 Size: `{lot_size_from_alert}` BTC\n" \
                     f"📉 Strategy: Limit order will execute when price comes to `${entry_price}`"
            log_and_notify(message)
            
            cancel_all_orders()
            # ✅ Place limit order for short entry (your strategy)
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
            message = f"🚪 *{alert_type.replace('_', ' ')} SIGNAL RECEIVED*\n" \
                     f"📊 Current Price: `${current_price or 'N/A'}`"
            log_and_notify(message)
            close_position()
            
        else:
            error_msg = f"⚠️ *UNKNOWN ALERT TYPE: {alert_type}*"
            log_and_notify(error_msg, "warning")
            return jsonify({"status": "error", "message": "Unknown alert type"}), 400
        
        return jsonify({"status": "success", "message": "Alert processed", "current_price": current_price})
    
    except Exception as e:
        error_msg = f"❌ *WEBHOOK ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Get current trading status - ENHANCED VERSION"""
    try:
        current_pos = get_position_data()
        current_price = get_current_price()
        
        orders_result = make_api_request('GET', '/orders', params={"product_ids": str(PRODUCT_ID), "states": "open"})
        open_orders = []
        
        if orders_result and orders_result.get('success'):
            open_orders = orders_result.get('result', [])
        
        message = f"📊 *TRADING STATUS*\n" \
                 f"🎯 Symbol: `{SYMBOL}` (ID: {PRODUCT_ID})\n" \
                 f"💰 Current Price: `${current_price or 'N/A'}`\n" \
                 f"📈 Position Status: `{current_position or 'None'}`\n" \
                 f"📋 Open Orders: `{len(open_orders)}`\n" \
                 f"🛡️ Stop Loss Orders: `{len(stop_loss_orders)}`\n" \
                 f"⏳ Pending SL Orders: `{len(pending_stop_losses)}`"
        
        if current_pos:
            pos_size = current_pos.get('size', 0)
            entry_price = current_pos.get('entry_price', 'N/A')
            margin = current_pos.get('margin', 'N/A')
            unrealized_pnl = current_pos.get('unrealized_pnl', 'N/A')
            message += f"\n\n💼 *POSITION DETAILS*\n" \
                      f"📏 Size: `{pos_size}` contracts\n" \
                      f"💵 Entry: `${entry_price}`\n" \
                      f"🏦 Margin: `${margin}`\n" \
                      f"📈 Unrealized PnL: `${unrealized_pnl}`"
        
        if open_orders:
            message += f"\n\n📋 *OPEN ORDERS*\n"
            for i, order in enumerate(open_orders[:3]):  # Show max 3 orders
                order_id = order.get('id', 'N/A')
                order_side = order.get('side', 'N/A').upper()
                order_size = order.get('size', 'N/A')
                order_price = order.get('limit_price', order.get('stop_price', 'N/A'))
                order_type = order.get('order_type', 'N/A')
                message += f"• `{order_id}` | {order_side} | {order_size} @ ${order_price} ({order_type})\n"
        
        log_and_notify(message)
        
        return jsonify({
            "status": "success",
            "current_price": current_price,
            "position": current_pos,
            "open_orders_count": len(open_orders),
            "stop_loss_orders": len(stop_loss_orders),
            "pending_stop_losses": len(pending_stop_losses)
        })
        
    except Exception as e:
        error_msg = f"❌ *STATUS CHECK ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/cancel_all', methods=['POST'])
def cancel_all_orders_endpoint():
    """Cancel all orders endpoint"""
    try:
        cancel_all_orders()
        message = "🗑️ *ALL ORDERS CANCELLATION REQUESTED*"
        log_and_notify(message)
        return jsonify({"status": "success", "message": "All orders cancelled"})
    except Exception as e:
        error_msg = f"❌ *CANCEL ALL ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/close_position', methods=['POST'])
def close_position_endpoint():
    """Close position endpoint"""
    try:
        close_position()
        return jsonify({"status": "success", "message": "Position close requested"})
    except Exception as e:
        error_msg = f"❌ *CLOSE POSITION ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test API connectivity
        product = verify_product()
        current_price = get_current_price()
        
        if product and current_price:
            return jsonify({
                "status": "healthy",
                "api_connection": "ok",
                "product_verified": True,
                "current_price": current_price,
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "unhealthy",
                "api_connection": "failed",
                "product_verified": False,
                "timestamp": datetime.now().isoformat()
            }), 503
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/test_telegram', methods=['POST'])
def test_telegram():
    """Test Telegram notification"""
    try:
        test_message = "🧪 *TELEGRAM TEST MESSAGE*\n" \
                      f"✅ Bot is working correctly!\n" \
                      f"⏰ Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        send_telegram_message(test_message)
        return jsonify({"status": "success", "message": "Test message sent"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Initialize bot on startup
def initialize_bot():
    """Initialize bot and send startup message"""
    try:
        logger.info("🚀 Starting Delta Trading Bot...")
        
        # Verify product
        product = verify_product()
        if not product:
            error_msg = "❌ *BOT STARTUP FAILED*\n🚨 Product verification failed"
            log_and_notify(error_msg, "error")
            return False
        
        # Get current price
        current_price = get_current_price()
        
        # Send startup message
        startup_message = f"🚀 *DELTA TRADING BOT STARTED*\n" \
                         f"🎯 Symbol: `{SYMBOL}` (ID: {PRODUCT_ID})\n" \
                         f"💰 Current Price: `${current_price or 'N/A'}`\n" \
                         f"📏 Default Lot Size: `{LOT_SIZE}` BTC\n" \
                         f"✅ Product Status: `{product.get('trading_status', 'N/A')}`\n" \
                         f"🌐 Webhook URL: `/webhook`\n" \
                         f"📊 Status URL: `/status`\n" \
                         f"⏰ Started at: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        
        log_and_notify(startup_message)
        logger.info("✅ Bot initialized successfully")
        return True
        
    except Exception as e:
        error_msg = f"❌ *BOT INITIALIZATION ERROR*\n🚨 Error: `{str(e)}`"
        log_and_notify(error_msg, "error")
        return False

if __name__ == '__main__':
    # Initialize bot
    if initialize_bot():
        logger.info("🌐 Starting Flask server...")
        # Run Flask app
        app.run(
            host='0.0.0.0',  # Allow external connections
            port=5000,       # Port number
            debug=False,     # Set to False for production
            threaded=True    # Enable threading for concurrent requests
        )
    else:
        logger.error("❌ Bot initialization failed. Exiting...")
        exit(1)

