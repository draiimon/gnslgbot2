import os
import json
import time
from datetime import datetime
from pathlib import Path
import sys

import firebase_admin
from firebase_admin import credentials, firestore

class FirebaseDB:
    """Firebase database manager for Ginsilog Bot (Production mode with no memory fallback)"""
    
    def __init__(self):
        """Initialize Firebase connection and collections in production mode"""
        # Path to service account credentials
        self.connected = False
        cred_paths = [
            Path("firebase-credentials.json"),  # Standard path
            Path("/app/firebase-credentials.json"),  # Docker/Render path
            Path("./firebase-credentials.json"),  # Alternative path
        ]
        
        # Search for credentials in multiple locations
        cred_file = None
        for path in cred_paths:
            if path.exists():
                cred_file = path
                break
        
        # Check if credentials exist in environment variable
        if not cred_file and 'FIREBASE_CREDENTIALS' in os.environ:
            # Create the file from environment variable
            cred_content = os.environ.get('FIREBASE_CREDENTIALS')
            if cred_content:
                with open('firebase-credentials.json', 'w') as f:
                    f.write(cred_content)
                os.chmod('firebase-credentials.json', 0o600)  # Secure permissions
                print("Created Firebase credentials from environment variable")
                cred_file = Path('firebase-credentials.json')
        
        if not cred_file:
            print("❌ Firebase credentials not found in any location")
            print("❌ Please make sure to set the FIREBASE_CREDENTIALS environment variable")
            print("❌ Exiting as Firebase is required for the bot to function")
            sys.exit(1)
            
        try:
            # Initialize Firebase with credentials
            print(f"Initializing Firebase with credentials from {cred_file}")
            cred = credentials.Certificate(str(cred_file))
            # Check if Firebase app already initialized
            try:
                firebase_admin.initialize_app(cred)
            except ValueError as e:
                if "The default Firebase app already exists" in str(e):
                    print("✅ Firebase app already initialized, reusing existing connection")
                else:
                    raise
            
            # Get Firestore client
            self.db = firestore.client()
            self.connected = True
            print("✅ Connected to Firebase Firestore in PRODUCTION MODE")
            
        except Exception as e:
            print(f"❌ Firebase initialization error: {e}")
            if "The default Firebase app already exists" in str(e):
                # Continue with the existing Firebase app
                print("✅ Continuing with existing Firebase app")
                self.db = firestore.client()
                self.connected = True
                return
            else:
                # For other errors, exit
                print("❌ Exiting as Firebase is required for the bot to function")
                sys.exit(1)
    
    def get_user_balance(self, user_id):
        """Get user's balance from the database"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Get user document
            doc_ref = self.db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            
            # If user doesn't exist, create new user with default balance
            if not doc.exists:
                default_balance = 50000
                doc_ref.set({
                    "user_id": str(user_id),
                    "balance": default_balance,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "last_daily": None
                })
                return default_balance
            
            # Return balance
            user_data = doc.to_dict()
            return user_data.get("balance", 50000)
            
        except Exception as e:
            print(f"❌ Error getting user balance: {e}")
            raise Exception("Firebase connection required")
    
    def add_coins(self, user_id, amount):
        """Add coins to user's balance"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Get current balance
            current_balance = self.get_user_balance(user_id)
            
            # Update balance
            new_balance = current_balance + amount
            
            # Update user document
            doc_ref = self.db.collection('users').document(str(user_id))
            doc_ref.update({"balance": new_balance})
            
            return new_balance
            
        except Exception as e:
            print(f"❌ Error adding coins: {e}")
            raise Exception("Firebase connection required")
    
    def deduct_coins(self, user_id, amount):
        """Deduct coins from user's balance"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Get current balance
            current_balance = self.get_user_balance(user_id)
            
            # Check if user has enough coins
            if current_balance < amount:
                return None
            
            # Update balance
            new_balance = current_balance - amount
            
            # Update user document
            doc_ref = self.db.collection('users').document(str(user_id))
            doc_ref.update({"balance": new_balance})
            
            return new_balance
            
        except Exception as e:
            print(f"❌ Error deducting coins: {e}")
            raise Exception("Firebase connection required")
    
    def update_daily_cooldown(self, user_id):
        """Update user's daily claim timestamp"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Update user document
            doc_ref = self.db.collection('users').document(str(user_id))
            doc_ref.update({"last_daily": firestore.SERVER_TIMESTAMP})
            
            return True
            
        except Exception as e:
            print(f"❌ Error updating daily cooldown: {e}")
            raise Exception("Firebase connection required")
    
    def get_daily_cooldown(self, user_id):
        """Get user's last daily claim timestamp"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Get user document
            doc_ref = self.db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            
            # If user doesn't exist or has no daily cooldown, return None
            if not doc.exists:
                return None
            
            user_data = doc.to_dict()
            return user_data.get("last_daily")
            
        except Exception as e:
            print(f"❌ Error getting daily cooldown: {e}")
            raise Exception("Firebase connection required")
    
    def add_rate_limit_entry(self, user_id):
        """Add a rate limit entry for a user"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Create unique ID for rate limit entry
            entry_id = f"{user_id}_{int(time.time())}"
            
            # Add rate limit entry
            self.db.collection('rate_limits').document(entry_id).set({
                "user_id": str(user_id),
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            
            return True
            
        except Exception as e:
            print(f"❌ Error adding rate limit entry: {e}")
            raise Exception("Firebase connection required")
    
    def is_rate_limited(self, user_id, limit=5, period_seconds=60):
        """Check if user is rate limited"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Calculate time threshold
            threshold = datetime.now().timestamp() - period_seconds
            
            # Query recent entries
            query = self.db.collection('rate_limits') \
                .where('user_id', '==', str(user_id)) \
                .where('timestamp', '>', firestore.Timestamp.from_date(
                    datetime.fromtimestamp(threshold)
                ))
            
            # Count results
            entries = list(query.stream())
            return len(entries) >= limit
            
        except Exception as e:
            print(f"❌ Error checking rate limit: {e}")
            raise Exception("Firebase connection required")
    
    def clear_old_rate_limits(self):
        """Clean up old rate limit entries (older than 1 hour)"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Calculate time threshold (1 hour ago)
            threshold = datetime.now().timestamp() - 3600
            
            # Query old entries
            query = self.db.collection('rate_limits') \
                .where('timestamp', '<', firestore.Timestamp.from_date(
                    datetime.fromtimestamp(threshold)
                ))
            
            # Delete old entries
            entries = list(query.stream())
            batch = self.db.batch()
            
            for entry in entries:
                batch.delete(entry.reference)
            
            # Commit batch delete
            if entries:
                batch.commit()
            
            return len(entries)
            
        except Exception as e:
            print(f"❌ Error clearing old rate limits: {e}")
            raise Exception("Firebase connection required")
    
    def add_to_conversation(self, channel_id, is_user, content):
        """Add a message to the conversation history"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Add message document
            self.db.collection('conversations').add({
                "channel_id": str(channel_id),
                "is_user": is_user,
                "content": content,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            
            return True
            
        except Exception as e:
            print(f"❌ Error adding to conversation: {e}")
            raise Exception("Firebase connection required")
    
    def get_conversation_history(self, channel_id, limit=10):
        """Get recent conversation history for a channel"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Query recent messages
            query = self.db.collection('conversations') \
                .where('channel_id', '==', str(channel_id)) \
                .order_by('timestamp', direction=firestore.Query.DESCENDING) \
                .limit(limit)
            
            # Get results
            messages = list(query.stream())
            
            # Convert to list of dicts with required fields
            history = [
                {"is_user": msg.to_dict()["is_user"], "content": msg.to_dict()["content"]}
                for msg in messages
            ]
            
            # Reverse to get chronological order
            history.reverse()
            
            return history
            
        except Exception as e:
            print(f"❌ Error getting conversation history: {e}")
            # Return an empty list instead of failing completely
            # This enables graceful degradation when Firestore indexes aren't created yet
            return []
    
    def clear_conversation_history(self, channel_id):
        """Clear conversation history for a channel"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Query all messages for this channel
            query = self.db.collection('conversations') \
                .where('channel_id', '==', str(channel_id))
            
            # Delete messages in batches
            messages = list(query.stream())
            batch = self.db.batch()
            count = 0
            
            for msg in messages:
                batch.delete(msg.reference)
                count += 1
                
                # Firestore batch has a limit of 500 operations
                if count % 400 == 0:
                    batch.commit()
                    batch = self.db.batch()
            
            # Commit final batch
            if count % 400 != 0:
                batch.commit()
            
            return count
            
        except Exception as e:
            print(f"❌ Error clearing conversation history: {e}")
            raise Exception("Firebase connection required")
    
    def save_blackjack_game(self, user_id, player_hand, dealer_hand, bet, game_state="in_progress"):
        """Save blackjack game state"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Update blackjack document
            doc_ref = self.db.collection('blackjack').document(str(user_id))
            doc_ref.set({
                "player_hand": player_hand,
                "dealer_hand": dealer_hand,
                "bet": bet,
                "game_state": game_state,
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            
            return True
            
        except Exception as e:
            print(f"❌ Error saving blackjack game: {e}")
            raise Exception("Firebase connection required")
    
    def get_blackjack_game(self, user_id):
        """Get blackjack game state"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Get blackjack document
            doc_ref = self.db.collection('blackjack').document(str(user_id))
            doc = doc_ref.get()
            
            if not doc.exists:
                return None
            
            # Get game data
            game_data = doc.to_dict()
            
            return {
                "player_hand": game_data["player_hand"],
                "dealer_hand": game_data["dealer_hand"],
                "bet": game_data["bet"],
                "game_state": game_data["game_state"]
            }
            
        except Exception as e:
            print(f"❌ Error getting blackjack game: {e}")
            raise Exception("Firebase connection required")
    
    def delete_blackjack_game(self, user_id):
        """Delete blackjack game state"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Delete blackjack document
            doc_ref = self.db.collection('blackjack').document(str(user_id))
            doc_ref.delete()
            
            return True
            
        except Exception as e:
            print(f"❌ Error deleting blackjack game: {e}")
            raise Exception("Firebase connection required")
    
    def get_leaderboard(self, limit=10):
        """Get top users by balance"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Query users ordered by balance
            query = self.db.collection('users') \
                .order_by('balance', direction=firestore.Query.DESCENDING) \
                .limit(limit)
            
            # Get results
            users = list(query.stream())
            
            # Convert to list of dicts with required fields
            leaderboard = [
                {"user_id": user.to_dict()["user_id"], 
                 "balance": user.to_dict()["balance"]}
                for user in users
            ]
            
            return leaderboard
            
        except Exception as e:
            print(f"❌ Error getting leaderboard: {e}")
            raise Exception("Firebase connection required")
    
    def get_user_stats(self, user_id):
        """Get comprehensive user statistics"""
        if not self.connected:
            raise Exception("Firebase connection required")
        
        try:
            # Get user document
            doc_ref = self.db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            
            if not doc.exists:
                return {"balance": 50000}
            
            # Get user data
            user_data = doc.to_dict()
            
            # Return stats
            return {
                "user_id": user_id,
                "balance": user_data.get("balance", 50000),
                "last_daily": user_data.get("last_daily"),
                "created_at": user_data.get("created_at")
            }
            
        except Exception as e:
            print(f"❌ Error getting user stats: {e}")
            raise Exception("Firebase connection required")
    
    def get_user_voice_preference(self, user_id):
        """Get user's voice preference from database"""
        if not self.connected:
            raise Exception("Firebase connection required for voice preferences")
        
        try:
            # Get user document
            doc_ref = self.db.collection('audio_preferences').document(str(user_id))
            doc = doc_ref.get()
            
            # If user doesn't exist, return default voice
            if not doc.exists:
                return "f"  # Default to female voice
            
            # Return voice preference
            prefs = doc.to_dict()
            return prefs.get("voice", "f")
            
        except Exception as e:
            print(f"❌ Error getting user voice preference: {e}")
            raise Exception("Firebase connection required for voice preferences")
    
    def set_user_voice_preference(self, user_id, voice_type):
        """Set user's voice preference in database"""
        if not self.connected:
            raise Exception("Firebase connection required for voice preferences")
        
        try:
            # Update audio preferences document
            doc_ref = self.db.collection('audio_preferences').document(str(user_id))
            doc_ref.set({
                "user_id": str(user_id),
                "voice": voice_type,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            
            return True
            
        except Exception as e:
            print(f"❌ Error setting user voice preference: {e}")
            raise Exception("Firebase connection required for voice preferences")
            
    def get_auto_tts_channels(self):
        """Get auto TTS channel settings from database"""
        if not self.connected:
            raise Exception("Firebase connection required for auto TTS settings")
            
        try:
            # Get all auto TTS settings documents
            collection_ref = self.db.collection('auto_tts_settings')
            docs = collection_ref.get()
            
            # Convert to dictionary format {guild_id: [channel_ids]}
            result = {}
            for doc in docs:
                guild_data = doc.to_dict()
                result[doc.id] = guild_data.get('channels', [])
                
            return result
            
        except Exception as e:
            print(f"❌ Error getting auto TTS settings: {e}")
            raise Exception("Firebase connection required for auto TTS settings")
            
    def toggle_auto_tts_channel(self, guild_id, channel_id):
        """Toggle auto TTS for a channel in database"""
        if not self.connected:
            raise Exception("Firebase connection required for auto TTS settings")
            
        try:
            # Get existing settings
            guild_id_str = str(guild_id)
            channel_id_str = str(channel_id)
            
            # Get guild document
            doc_ref = self.db.collection('auto_tts_settings').document(guild_id_str)
            doc = doc_ref.get()
            
            # Initialize if doesn't exist
            if not doc.exists:
                channels = []
                enabled = True  # Will be enabled
            else:
                # Get current channels
                guild_data = doc.to_dict()
                channels = guild_data.get('channels', [])
                
                # Toggle channel
                if channel_id_str in channels:
                    channels.remove(channel_id_str)
                    enabled = False
                else:
                    channels.append(channel_id_str)
                    enabled = True
                    
            # Update document
            doc_ref.set({
                'channels': channels,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)
            
            return enabled
            
        except Exception as e:
            print(f"❌ Error toggling auto TTS channel: {e}")
            raise Exception("Firebase connection required for auto TTS settings")