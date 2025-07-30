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

# Delta Exchange API Configuration
BASE_URL = 'https://api.india.delta.exchange'
API_KEY = 'NWczUdbI9vVbBlCASC0rRFolMpPM32'  # Replace with your actual API key
API_SECRET = 'YTN79e7x2vuLSYzGW7YUBMnZNJEXTDPxsMaEpH0ZwXptQRwl9zjEby0Z8oAp'  # Replace with your actual API secret

# Telegram Configuration
TELEGRAM_BOT_TOKEN = '8068558939:AAHcsThdbt0J1uzI0mT140H9vJXbcaVZ9Jk'  # Replace with your actual token
TELEGRAM_CHAT_ID = '871704959'  # Replace with your actual chat ID
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

# Trading Configuration
SYMBOL = 'BTCUSD'
PRODUCT_ID = 27
LOT_SIZE = 0.005

# Enhanced Configuration
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = (5, 30)

# Global variables
current_position = None
active_orders = {}
pending_orders = {}

def send_telegram_message(message):
    """Enhanced Telegram messaging with error handling"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"🤖 Delta Trading Bot\n⏰ {timestamp}\n\n{message}"

        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': full_message,
            'parse_mode': 'Markdown'
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(TELEGRAM_API_URL, json=payload, timeout=10)
                if response.status_code == 200:
                    logger.info(f"✅ Telegram message sent successfully (attempt {attempt + 1})")
                    return True
                else:
                    logger.warning(f"⚠️ Telegram attempt {attempt + 1} failed: {response.status_code}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
            except Exception as e:
                logger.warning(f"⚠️ Telegram attempt {attempt + 1} error: {str(e)}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        
        logger.error("❌ All Telegram attempts failed")
        return False
        
    except Exception as e:
        logger.error(f"❌ Critical Telegram error: {str(e)}")
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
    """Enhanced API request with comprehensive error handling and retries"""
    request_id = f"REQ_{int(time.time() * 1000)}"
    
    logger.info(f"🚀 [{request_id}] Starting {method} request to {endpoint}")
    logger.info(f"📤 [{request_id}] Payload: {payload}")
    logger.info(f"📤 [{request_id}] Params: {params}")
    
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
        'User-Agent': 'amogh-smc-bot/2.0',
        'Content-Type': 'application/json'
    }

    logger.info(f"🔐 [{request_id}] Headers prepared, timestamp: {timestamp}")

    # Retry mechanism
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"🔄 [{request_id}] Attempt {attempt + 1}/{MAX_RETRIES}")
            
            start_time = time.time()
            
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            elif method == 'POST':
                response = requests.post(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, data=payload, params=params, timeout=REQUEST_TIMEOUT)
            else:
                logger.error(f"❌ [{request_id}] Unsupported method: {method}")
                return False, {"error": "Unsupported HTTP method"}

            response_time = time.time() - start_time
            logger.info(f"📥 [{request_id}] Response received in {response_time:.3f}s")
            logger.info(f"📊 [{request_id}] Status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    logger.info(f"✅ [{request_id}] Request successful")
                    logger.debug(f"📋 [{request_id}] Response data: {json.dumps(response_data, indent=2)}")
                    return True, response_data
                except json.JSONDecodeError as e:
                    logger.error(f"❌ [{request_id}] JSON decode error: {str(e)}")
                    logger.error(f"📄 [{request_id}] Raw response: {response.text}")
                    return False, {"error": "Invalid JSON response", "raw_response": response.text}
            
            else:
                error_data = {
                    "status_code": response.status_code,
                    "reason": response.reason,
                    "raw_response": response.text
                }
                
                try:
                    error_json = response.json()
                    error_data.update(error_json)
                except:
                    pass
                
                logger.error(f"❌ [{request_id}] HTTP Error {response.status_code}: {response.reason}")
                logger.error(f"📄 [{request_id}] Response: {response.text}")
                
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
                logger.warning(f"⏳ [{request_id}] Retrying after timeout...")
                time.sleep(RETRY_DELAY)
                continue
            return False, {"error": "Request timeout", "details": str(e)}

        except requests.exceptions.ConnectionError as e:
            logger.error(f"🔌 [{request_id}] Connection error: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"⏳ [{request_id}] Retrying after connection error...")
                time.sleep(RETRY_DELAY)
                continue
            return False, {"error": "Connection error", "details": str(e)}

        except Exception as e:
            logger.error(f"💥 [{request_id}] Unexpected error: {str(e)}")
            logger.error(f"📋 [{request_id}] Traceback: {traceback.format_exc()}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return False, {"error": "Unexpected error", "details": str(e)}

    return False, {"error": "Max retries exceeded"}

def validate_webhook_data(data: Dict) -> Tuple[bool, str]:
    """Validate incoming webhook data"""
    if not data:
        return False, "No data received"
    
    required_fields = ['alert_type', 'stop_price']
    missing_fields = []
    
    for field in required_fields:
        if field not in data:
            missing_fields.append(field)
        elif data[field] is None:
            missing_fields.append(f"{field} (None)")
        elif str(data[field]).strip() == '':
            missing_fields.append(f"{field} (empty)")
    
    if missing_fields:
        return False, f"Missing/invalid fields: {', '.join(missing_fields)}"
    
    # Validate alert_type
    valid_alert_types = ['LONG_ENTRY', 'SHORT_ENTRY', 'LONG_EXIT', 'SHORT_EXIT']
    if data['alert_type'] not in valid_alert_types:
        return False, f"Invalid alert_type: {data['alert_type']}. Must be one of: {valid_alert_types}"
    
    # Validate stop_price
    try:
        stop_price = float(data['stop_price'])
        if stop_price <= 0:
            return False, f"Invalid stop_price: {stop_price}. Must be positive"
    except (ValueError, TypeError) as e:
        return False, f"Invalid stop_price format: {data['stop_price']} - {str(e)}"
    
    return True, "Validation passed"

def get_current_price():
    """Get current market price with enhanced error handling"""
    logger.info("📊 Getting current market price")
    
    success, result = make_api_request('GET', f'/products/{PRODUCT_ID}/ticker')
    
    if success and result and result.get('success'):
        price = float(result['result']['mark_price'])
        logger.info(f"💰 Current price: ${price}")
        return price
    else:
        logger.error(f"❌ Failed to get current price: {result}")
        return None

def get_order_status(order_id):
    """Get order status by order ID with enhanced error handling"""
    logger.info(f"🔍 Getting status for order {order_id}")
    
    try:
        success, result = make_api_request('GET', f'/orders/{order_id}')
        
        if success and result and result.get('success'):
            order_data = result.get('result')
            if order_data:
                state = order_data.get('state', 'unknown')
                logger.info(f"📋 Order {order_id} status: {state}")
                return order_data
            else:
                logger.warning(f"⚠️ No order data in response for {order_id}")
                return None
        else:
            error_details = result.get('error', 'Unknown error') if result else 'No response'
            logger.error(f"❌ Failed to get order status for {order_id}: {error_details}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Exception getting order status for {order_id}: {str(e)}")
        return None

def get_position_data():
    """Get position data with enhanced error handling"""
    logger.info("📊 Getting position data")
    
    try:
        # Try regular positions first
        params = {"product_id": PRODUCT_ID}
        success, result = make_api_request('GET', '/positions', params=params)
        
        if success and result and result.get('success'):
            position_data = result.get('result')
            if position_data and position_data.get('size', 0) != 0:
                logger.info(f"📍 Position found: {position_data.get('size')} contracts")
                return position_data
        
        # Fallback to margined positions
        params = {"product_ids": str(PRODUCT_ID)}
        success, result = make_api_request('GET', '/positions/margined', params=params)
        
        if success and result and result.get('success'):
            positions = result.get('result', [])
            for pos in positions:
                if (pos.get('product_symbol') == SYMBOL or pos.get('product_id') == PRODUCT_ID) and pos.get('size', 0) != 0:
                    logger.info(f"📍 Margined position found: {pos.get('size')} contracts")
                    return pos
        
        logger.info("📍 No position found")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error getting position data: {str(e)}")
        logger.error(f"📋 Traceback: {traceback.format_exc()}")
        return None

def cancel_all_orders():
    """Cancel all open orders"""
    try:
        log_and_notify("❎ Cancelling all open orders...")
        
        # Use the correct endpoint from Delta Exchange API
        payload = json.dumps({
            "product_id": PRODUCT_ID,
            "cancel_limit_orders": "true",
            "cancel_stop_orders": "true",
            "cancel_reduce_only_orders": "true"
        })
        
        success, result = make_api_request('DELETE', '/orders/all', payload)
        
        if success and result and result.get('success'):
            log_and_notify("✅ All open orders cancelled successfully.")
        else:
            error_details = result.get('error', 'Unknown error') if result else 'No response'
            log_and_notify(f"⚠️ Failed to cancel all orders: {error_details}", level="error")
            
    except Exception as e:
        log_and_notify(f"❌ ERROR cancelling all orders: {str(e)}", level="error")
        logger.error(f"📋 Traceback: {traceback.format_exc()}")

def close_position():
    """Close current position at market"""
    try:
        log_and_notify("🔄 Checking for position to close...")
        
        position = get_position_data()
        if position and position.get('size', 0) != 0:
            position_size = int(position['size'])
            side = 'sell' if position_size > 0 else 'buy'  # Long position = sell to close, Short = buy to close
            size = abs(position_size) / 1000.0  # Convert contracts to BTC
            
            log_and_notify(f"📍 Found position: {position_size} contracts")
            log_and_notify(f"🚪 Closing position with {side.upper()} market order")
            
            order_id = place_market_order(side, size)
            if order_id:
                log_and_notify("✅ Position close order placed successfully")
            else:
                log_and_notify("❌ Failed to place position close order", level="error")
        else:
            log_and_notify("ℹ️ No open position to close.")
            
    except Exception as e:
        log_and_notify(f"❌ ERROR closing position: {str(e)}", level="error")
        logger.error(f"📋 Traceback: {traceback.format_exc()}")

def monitor_order(order_id, side, entry_price, stop_loss, size):
    """Monitor a pending order and manage SL"""
    try:
        log_and_notify(f"👀 Monitoring order {order_id}...", request_id=order_id)
        
        filled = False
        max_wait_time = 600  # 10 minutes
        check_interval = 2   # Check every 2 seconds
        
        for i in range(0, max_wait_time, check_interval):
            try:
                order = get_order_status(order_id)
                if order:
                    order_state = order.get('state', 'unknown')
                    logger.info(f"📊 [{order_id}] Order state: {order_state}")
                    
                    if order_state == 'filled':
                        filled = True
                        filled_size = order.get('size_filled', 0)
                        avg_fill_price = order.get('average_fill_price', entry_price)
                        
                        log_and_notify(
                            f"✅ ORDER {order_id} FILLED!\n"
                            f"📏 Size: {filled_size} contracts\n"
                            f"💰 Avg Price: ${avg_fill_price}\n"
                            f"📍 Position activated.",
                            request_id=order_id
                        )
                        
                        # Update global position status
                        global current_position
                        current_position = 'long' if side == 'buy' else 'short'
                        
                        # Remove from pending orders
                        if order_id in pending_orders:
                            del pending_orders[order_id]
                        
                        break
                    elif order_state in ['cancelled', 'rejected']:
                        log_and_notify(
                            f"❌ Order {order_id} was {order_state}",
                            request_id=order_id
                        )
                        # Clean up
                        if order_id in pending_orders:
                            del pending_orders[order_id]
                        current_position = None
                        break
                        
                else:
                    logger.warning(f"⚠️ [{order_id}] Could not get order status")
                
                time.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"❌ [{order_id}] Error checking order status: {str(e)}")
                time.sleep(check_interval)

        if not filled:
            log_and_notify(
                f"⌛ Order {order_id} not filled in {max_wait_time//60} minutes. Cancelling...",
                request_id=order_id
            )
            
            # Cancel the unfilled order
            cancel_payload = json.dumps({"id": order_id, "product_id": PRODUCT_ID})
            success, result = make_api_request('DELETE', '/orders', cancel_payload)
            
            if success:
                log_and_notify(f"✅ Order {order_id} cancelled successfully", request_id=order_id)
            else:
                log_and_notify(f"⚠️ Failed to cancel order {order_id}", level="error", request_id=order_id)
            
            # Clean up
            if order_id in pending_orders:
                del pending_orders[order_id]
            current_position = None

    except Exception as e:
        log_and_notify(f"❌ ERROR in monitor_order: {str(e)}", level="error")
        logger.error(f"📋 Traceback: {traceback.format_exc()}")
        
        # Clean up on error
        if order_id in pending_orders:
            del pending_orders[order_id]

def place_entry_order(side, stop_price, size, request_id=None):
    """Place stop-market order using Delta's supported schema"""
    try:
        contracts = max(1, int(size * 1000))
        stop_price = float(stop_price)
        formatted_stop = f"{stop_price:.2f}"

        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "limit_order",  # ✅ Required
            "stop_order_type": "stop_market_order",  # ✅ Real stop type
            "stop_price": formatted_stop,
            "stop_trigger_method": "last_traded_price",
            "time_in_force": "gtc"  # Good till cancel
        }

        log_and_notify(f"📈 Placing {side.upper()} STOP-MARKET order\n"
                      f"🔫 Trigger: ${formatted_stop}\n"
                      f"📏 Size: {size} BTC ({contracts} contracts)", 
                      request_id=request_id)

        payload = json.dumps(order_data)
        success, result = make_api_request('POST', '/orders/create', payload)


        if success and result and result.get('success'):
            order_id = result['result']['id']
            order_state = result['result'].get('state', 'unknown')
            
            log_and_notify(
                f"✅ {side.upper()} STOP-MARKET ORDER PLACED\n"
                f"🆔 Order ID: {order_id}\n"
                f"📏 Size: {contracts} contracts\n"
                f"📊 State: {order_state}\n"
                f"🕒 Waiting for trigger...",
                request_id=request_id
            )
            return order_id
        else:
            error_details = result.get('error', 'Unknown error') if result else 'No response'
            error_msg = f"❌ FAILED TO PLACE {side.upper()} ORDER\n" \
                       f"🚨 Error: {error_details}\n" \
                       f"📋 Full Response: {json.dumps(result, indent=2) if result else 'None'}"
            log_and_notify(error_msg, "error", request_id=request_id)
            return None

    except Exception as e:
        error_msg = f"❌ ORDER PLACEMENT ERROR\n" \
                   f"🚨 Error: {str(e)}\n" \
                   f"📋 Traceback: {traceback.format_exc()}"
        log_and_notify(error_msg, "error", request_id=request_id)
        return None


def place_market_order(side, size, request_id=None):
    """Place market order for exits with enhanced error handling"""
    try:
        contracts = max(1, int(size * 1000))
        order_data = {
            "product_id": PRODUCT_ID,
            "size": contracts,
            "side": side.lower(),
            "order_type": "market_order",
            "time_in_force": "ioc"
        }
        
        log_and_notify(f"⚡ Placing {side} market order\n📏 Size: {contracts} contracts", 
                      request_id=request_id)
        
        payload = json.dumps(order_data)
        success, result = make_api_request('POST', '/orders', payload)

        if success and result and result.get('success'):
            order_id = result['result']['id']
            order_state = result['result'].get('state', 'unknown')
            filled_size = result['result'].get('size_filled', 0)
            
            message = f"✅ {side.upper()} MARKET ORDER EXECUTED\n" \
                     f"🆔 Order ID: {order_id}\n" \
                     f"📏 Size: {contracts} contracts\n" \
                     f"📊 State: {order_state}\n" \
                     f"✅ Filled: {filled_size} contracts"
            log_and_notify(message, request_id=request_id)
            return order_id
        else:
            error_details = result.get('error', 'Unknown error') if result else 'No response'
            error_msg = f"❌ FAILED TO EXECUTE {side.upper()} ORDER\n" \
                       f"📏 Size: {contracts} contracts\n" \
                       f"🚨 Error: {error_details}\n" \
                       f"📋 Full Response: {json.dumps(result, indent=2) if result else 'None'}"
            log_and_notify(error_msg, "error", request_id=request_id)
            return None
            
    except Exception as e:
        error_msg = f"❌ MARKET ORDER ERROR\n" \
                   f"🚨 Error: {str(e)}\n" \
                   f"📋 Traceback: {traceback.format_exc()}"
        log_and_notify(error_msg, "error", request_id=request_id)
        return None

@app.route('/webhook', methods=['POST'])
def webhook():
    """Enhanced webhook handler with comprehensive error handling"""
    global current_position, pending_orders
    
    webhook_id = f"WH_{int(time.time() * 1000)}"
    start_time = time.time()
    
    logger.info(f"🎯 [{webhook_id}] Webhook request received")
    logger.info(f"📍 [{webhook_id}] Source IP: {request.remote_addr}")
    logger.info(f"📍 [{webhook_id}] Headers: {dict(request.headers)}")

    try:
        # Step 1: Get request data
        logger.info(f"📋 [{webhook_id}] Step 1: Extracting request data")
        
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        logger.info(f"📨 [{webhook_id}] Raw data received: {json.dumps(data, indent=2)}")

        # Step 2: Validate data
        logger.info(f"🔍 [{webhook_id}] Step 2: Validating webhook data")
        
        is_valid, validation_msg = validate_webhook_data(data)
        if not is_valid:
            error_msg = f"❌ WEBHOOK VALIDATION FAILED\n🚨 Error: {validation_msg}"
            log_and_notify(error_msg, "error", webhook_id)
            return jsonify({
                "status": "error", 
                "message": validation_msg,
                "webhook_id": webhook_id
            }), 400

        # Step 3: Extract parameters
        logger.info(f"⚙️ [{webhook_id}] Step 3: Processing parameters")
        
        alert_type = data.get('alert_type')
        stop_price = float(data.get("stop_price"))
        stop_loss = float(data.get('stop_loss', 0))
        size = float(data.get('lot_size', LOT_SIZE))

        logger.info(f"📊 [{webhook_id}] Processed parameters:")
        logger.info(f"   Alert Type: {alert_type}")
        logger.info(f"   Stop Price: {stop_price}")
        logger.info(f"   Stop Loss: {stop_loss}")
        logger.info(f"   Size: {size}")

        # Step 4: Process alert
        logger.info(f"🚀 [{webhook_id}] Step 4: Processing {alert_type} alert")

        if alert_type == 'LONG_ENTRY':
            log_and_notify(f"🟢 LONG ENTRY SIGNAL\n🔫 Stop: {stop_price} | 🛑 SL: {stop_loss}", 
                          request_id=webhook_id)
            cancel_all_orders()
            order_id = place_entry_order('buy', stop_price, size, webhook_id)
            if order_id:
                current_position = 'long_pending'
                pending_orders[order_id] = {
                    'type': 'entry',
                    'side': 'buy',
                    'price': stop_price,
                    'size': size,
                    'stop_loss': stop_loss,
                    'webhook_id': webhook_id
                }
                threading.Thread(
                    target=monitor_order,
                    args=(order_id, 'buy', stop_price, stop_loss, size),
                    daemon=True
                ).start()

        elif alert_type == 'SHORT_ENTRY':
            log_and_notify(f"🔴 SHORT ENTRY SIGNAL\n🔫 Stop: {stop_price} | 🛑 SL: {stop_loss}", 
                          request_id=webhook_id)
            cancel_all_orders()
            order_id = place_entry_order('sell', stop_price, size, webhook_id)
            if order_id:
                current_position = 'short_pending'
                pending_orders[order_id] = {
                    'type': 'entry',
                    'side': 'sell',
                    'price': stop_price,
                    'size': size,
                    'stop_loss': stop_loss,
                    'webhook_id': webhook_id
                }
                threading.Thread(
                    target=monitor_order,
                    args=(order_id, 'sell', stop_price, stop_loss, size),
                    daemon=True
                ).start()

        elif alert_type in ['LONG_EXIT', 'SHORT_EXIT']:
            log_and_notify(f"🚪 {alert_type.replace('_', ' ')} SIGNAL", request_id=webhook_id)
            close_position()
            current_position = None

        processing_time = time.time() - start_time
        logger.info(f"✅ [{webhook_id}] Webhook processed successfully in {processing_time:.3f}s")

        return jsonify({
            "status": "success",
            "webhook_id": webhook_id,
            "processing_time": processing_time,
            "alert_type": alert_type
        })

    except Exception as e:
        processing_time = time.time() - start_time
        error_msg = f"❌ WEBHOOK ERROR\n" \
                   f"🚨 Error: {str(e)}\n" \
                   f"📋 Traceback: {traceback.format_exc()}"
        log_and_notify(error_msg, "critical", webhook_id)
        
        return jsonify({
            "status": "error", 
            "message": str(e),
            "webhook_id": webhook_id,
            "processing_time": processing_time
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    ...

