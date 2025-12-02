import json
import re
import asyncio
import sys
import platform
from typing import Dict, Optional
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from price_fetcher import PriceFetcher

# Workaround for Python 3.14 compatibility issue with private attributes
# Python 3.14 changed how private attributes work, causing issues with some libraries
if sys.version_info >= (3, 14):
    try:
        # Try to patch the Updater class after Application is imported
        # This allows setting private attributes that Python 3.14 would normally block
        import telegram.ext._updater as updater_module
        if hasattr(updater_module, 'Updater'):
            Updater = updater_module.Updater
            # Store original __setattr__ if it exists
            if hasattr(Updater, '__setattr__'):
                original_setattr = Updater.__setattr__
                def patched_setattr(self, name, value):
                    try:
                        return original_setattr(self, name, value)
                    except AttributeError as e:
                        if "__dict__" in str(e) or "no attribute" in str(e).lower():
                            # Use object.__setattr__ as fallback for Python 3.14
                            return object.__setattr__(self, name, value)
                        raise
                Updater.__setattr__ = patched_setattr
    except (ImportError, AttributeError, Exception):
        # If patching fails, continue anyway - the library might handle it
        pass

class TokenMonitorBot:
    def __init__(self, token: str):
        self.token = token
        self.price_fetcher = PriceFetcher()
        self.monitoring_tasks = {}  # Store active monitoring tasks
        self.last_prices = {}  # Store last displayed prices to avoid duplicates
        
    def load_token_mapping(self) -> Dict:
        """Load token address mapping from token_mapping.json"""
        try:
            with open('token_mapping.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}
    
    def load_monitoring_config(self) -> Dict:
        """Load monitoring configuration from monitoring.json"""
        try:
            with open('monitoring.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}
    
    def save_monitoring_config(self, config: Dict):
        """Save monitoring configuration to monitoring.json"""
        with open('monitoring.json', 'w') as f:
            json.dump(config, f, indent=2)
    
    def parse_command(self, text: str) -> Optional[Dict]:
        """
        Parse command like 'kori 0.00237 0.00355'
        Returns dict with token_name, low, high or None if invalid
        Format: token_name X Y (where X is low value and Y is high value)
        """
        # Pattern: token_name low_value high_value
        # Allow scientific notation and decimal numbers
        pattern = r'^(\w+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)$'
        match = re.match(pattern, text.strip())
        
        if match:
            token_name = match.group(1).lower()
            try:
                low = float(match.group(2))
                high = float(match.group(3))
                return {
                    'token_name': token_name,
                    'low': low,
                    'high': high
                }
            except ValueError:
                return None
        return None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text(
            "Welcome to Token Price Monitor Bot!\n\n"
            "Commands:\n"
            "/price <token_name> - Check current price of a token\n"
            "/start - Show this help message\n\n"
            "To monitor a token, send:\n"
            "token_name X Y\n\n"
            "Where X is low value and Y is high value\n"
            "Example: kori 0.00237 0.00355"
        )
    
    async def price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /price command to check current token price"""
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                "Usage: /price <token_name>\n\n"
                "Example: /price kori"
            )
            return
        
        token_name = context.args[0].lower()
        
        # Check if token exists in mapping
        token_mapping = self.load_token_mapping()
        if token_name not in token_mapping:
            await update.message.reply_text(
                f"Error: Token '{token_name}' not found in token mapping.\n"
                f"Please add it to token_mapping.json first."
            )
            return
        
        token_info = token_mapping[token_name]
        address = token_info['address']
        chain = token_info['chain']
        
        # Send "fetching price" message
        status_msg = await update.message.reply_text(f"Fetching price for {token_name}...")
        
        # Fetch price
        price = self.price_fetcher.get_price(address, chain)
        
        if price is not None:
            await status_msg.edit_text(
                f"💰 {token_name.upper()}\n"
                f"Current Price: ${price:.12f}\n"
                f"Chain: {chain.upper()}\n"
                f"Address: {address[:8]}...{address[-8:]}"
            )
        else:
            await status_msg.edit_text(
                f"❌ Failed to fetch price for {token_name}.\n"
                f"Please check:\n"
                f"1. Token address is correct\n"
                f"2. Chain is correct ({chain})\n"
                f"3. Token exists on DEX platforms\n"
                f"4. Token has trading pairs with liquidity"
            )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages"""
        text = update.message.text
        chat_id = update.message.chat_id
        
        # Parse the command
        parsed = self.parse_command(text)
        
        if not parsed:
            await update.message.reply_text(
                "Invalid format. Please use:\n"
                "token_name X Y\n\n"
                "Where X is low value and Y is high value\n"
                "Example: kori 0.00237 0.00355"
            )
            return
        
        token_name = parsed['token_name']
        low = parsed['low']
        high = parsed['high']
        
        # Validate low < high
        if low >= high:
            await update.message.reply_text(
                "Error: Low price must be less than high price."
            )
            return
        
        # Check if token exists in mapping
        token_mapping = self.load_token_mapping()
        if token_name not in token_mapping:
            await update.message.reply_text(
                f"Error: Token '{token_name}' not found in token mapping. "
                f"Please add it to token_mapping.json first."
            )
            return
        
        # Update monitoring configuration
        monitoring_config = self.load_monitoring_config()
        monitoring_config[token_name] = {
            'low': low,
            'high': high,
            'chat_id': chat_id
        }
        self.save_monitoring_config(monitoring_config)
        
        # Stop existing monitoring task for this token if any
        if token_name in self.monitoring_tasks:
            self.monitoring_tasks[token_name].cancel()
        
        # Start monitoring
        await update.message.reply_text(
            f"Monitoring {token_name}:\n"
            f"Low threshold: {low}\n"
            f"High threshold: {high}\n\n"
            f"Starting price monitoring..."
        )
        
        # Start monitoring task
        task = asyncio.create_task(
            self.monitor_token(token_name, chat_id, context.bot)
        )
        self.monitoring_tasks[token_name] = task
    
    async def monitor_token(self, token_name: str, chat_id: int, bot):
        """Monitor token price every 8 seconds"""
        token_mapping = self.load_token_mapping()
        token_info = token_mapping[token_name]
        address = token_info['address']
        chain = token_info['chain']
        
        monitoring_config = self.load_monitoring_config()
        config = monitoring_config.get(token_name, {})
        low_threshold = config.get('low', 0)
        high_threshold = config.get('high', 0)
        
        price_displayed = False  # Track if price has been displayed once
        last_price = None  # Track last price to detect threshold crossings
        low_notified = False  # Track if low threshold notification was sent
        high_notified = False  # Track if high threshold notification was sent
        
        try:
            while True:
                # Fetch price
                price = self.price_fetcher.get_price(address, chain)
                
                if price is not None:
                    # Display price once
                    if not price_displayed:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"{token_name} current price: ${price:.12f}"
                        )
                        price_displayed = True
                        last_price = price
                    
                    # Check thresholds - only notify when crossing the threshold
                    if price <= low_threshold:
                        # Only notify if we haven't notified yet, or if price was above threshold before
                        if not low_notified or (last_price is not None and last_price > low_threshold):
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"{token_name} reached to low price"
                            )
                            low_notified = True
                            high_notified = False  # Reset high notification if price drops
                    elif price >= high_threshold:
                        # Only notify if we haven't notified yet, or if price was below threshold before
                        if not high_notified or (last_price is not None and last_price < high_threshold):
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"{token_name} reached to high price"
                            )
                            high_notified = True
                            low_notified = False  # Reset low notification if price rises
                    else:
                        # Price is between thresholds, reset notification states
                        if last_price is not None:
                            if last_price <= low_threshold and price > low_threshold:
                                low_notified = False
                            elif last_price >= high_threshold and price < high_threshold:
                                high_notified = False
                    
                    last_price = price
                    self.last_prices[token_name] = price
                
                # Wait 8 seconds
                await asyncio.sleep(8)
                
                # Reload config in case it was updated
                monitoring_config = self.load_monitoring_config()
                if token_name not in monitoring_config:
                    # Monitoring was stopped
                    break
                config = monitoring_config[token_name]
                new_low = config.get('low', 0)
                new_high = config.get('high', 0)
                
                # Reset notification states if thresholds changed
                if new_low != low_threshold or new_high != high_threshold:
                    low_notified = False
                    high_notified = False
                    low_threshold = new_low
                    high_threshold = new_high
                
        except asyncio.CancelledError:
            # Task was cancelled
            pass
        except Exception as e:
            print(f"Error in monitor_token for {token_name}: {e}")
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"Error monitoring {token_name}: {str(e)}"
                )
            except:
                pass

def main():
    """Main entry point that sets up the event loop for Python 3.14 compatibility"""
    # Load bot token from config.txt
    try:
        with open('config.txt', 'r') as f:
            bot_token = f.read().strip()
    except FileNotFoundError:
        print("Error: config.txt not found. Please create it with your bot token.")
        return
    
    if not bot_token:
        print("Error: Bot token is empty in config.txt")
        return
    
    try:
        # For Python 3.14 compatibility: set event loop policy and ensure loop exists
        # Python 3.14 changed asyncio.get_event_loop() to not create loops automatically
        if sys.version_info >= (3, 14):
            # Set WindowsSelectorEventLoopPolicy for Windows compatibility
            if platform.system() == 'Windows':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
            # Create and set a new event loop as the default
            # This ensures run_polling() can find it when it calls asyncio.get_event_loop()
            try:
                # Try to get existing loop first
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                # No event loop exists, create one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        
        # Create bot application
        application = Application.builder().token(bot_token).build()
        
        # Create bot instance
        bot_instance = TokenMonitorBot(bot_token)
        
        # Add handlers
        application.add_handler(CommandHandler("start", bot_instance.start))
        application.add_handler(CommandHandler("price", bot_instance.price_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_message))
        
        # Start bot
        print("Bot is starting...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except AttributeError as e:
        if "__polling_cleanup_cb" in str(e):
            print("Error: Compatibility issue with Python 3.14 detected.")
            print("Please try one of the following solutions:")
            print("1. Use Python 3.11 or 3.12 instead of Python 3.14")
            print("2. Wait for python-telegram-bot to release a Python 3.14 compatible version")
            print(f"Error details: {e}")
        else:
            raise
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
    except Exception as e:
        print(f"Error: {e}")
        raise

if __name__ == "__main__":
    main()

