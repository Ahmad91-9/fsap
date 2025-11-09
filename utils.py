import time
import random
import string
import hashlib

def debug_log(*args, **kwargs):
    """Simple debug logger — prints to stdout with timestamp."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{ts}]", *args, **kwargs)

def generate_referral_code(length=8, user_id=None):
    """
    Generate a unique referral code of specified length.
    Optionally uses user_id for more uniqueness.
    """
    characters = string.ascii_uppercase + string.digits
    max_attempts = 50
    
    for attempt in range(max_attempts):
        if user_id:
            # Use user_id + timestamp for more uniqueness
            seed = f"{user_id}_{int(time.time())}_{attempt}"
            hash_obj = hashlib.md5(seed.encode())
            hash_hex = hash_obj.hexdigest().upper()
            # Take first length characters, ensuring first is letter
            code = 'R' + ''.join(c for c in hash_hex if c.isalnum())[:length-1]
            if len(code) == length:
                return code
        
        # Fallback to random generation
        code = ''.join(random.choices(characters, k=length))
        # Ensure it starts with a letter
        if code[0].isalpha():
            return code
    
    # Ultimate fallback
    return 'REF' + ''.join(random.choices(string.digits, k=length-3))

def validate_referral_code(code):
    """Validate referral code format."""
    if not code:
        return True  # Empty code is valid (optional field)
    if not isinstance(code, str):
        return False
    if len(code) < 6 or len(code) > 12:
        return False
    if not code.isalnum():
        return False
    if not code[0].isalpha():
        return False
    return True

def format_referral_stats(active_count, total_count):
    """Format referral statistics for display."""
    if total_count == 0:
        return "No referrals yet"
    elif active_count == total_count:
        return f"{active_count} active referrals"
    else:
        return f"{active_count} active / {total_count} total referrals"

def generate_membership_code(length=8, user_id=None):
    """
    Generate a unique 8-character membership code (mix of digits and characters).
    Used to track which memberships have been used for reward calculations.
    """
    characters = string.ascii_uppercase + string.digits
    max_attempts = 50
    
    for attempt in range(max_attempts):
        if user_id:
            # Use user_id + timestamp for more uniqueness
            seed = f"{user_id}_{int(time.time())}_{attempt}"
            hash_obj = hashlib.md5(seed.encode())
            hash_hex = hash_obj.hexdigest().upper()
            # Take first length characters, ensuring mix of letters and digits
            code = ''.join(c for c in hash_hex if c.isalnum())[:length]
            if len(code) == length and any(c.isalpha() for c in code) and any(c.isdigit() for c in code):
                return code
        
        # Fallback to random generation
        code = ''.join(random.choices(characters, k=length))
        # Ensure it has both letters and digits
        if any(c.isalpha() for c in code) and any(c.isdigit() for c in code):
            return code
    
    # Ultimate fallback - ensure mix
    letters = ''.join(random.choices(string.ascii_uppercase, k=length//2))
    digits = ''.join(random.choices(string.digits, k=length - len(letters)))
    code = ''.join(random.sample(letters + digits, length))
    return code

def is_membership_expired(membership: bool, membership_expires: str) -> bool:
    """
    Check if a user's membership has expired.
    
    Args:
        membership: Boolean indicating if user has membership
        membership_expires: ISO format datetime string of when membership expires
        
    Returns:
        bool: True if membership has expired, False otherwise
    """
    # If no membership, consider it expired
    if not membership:
        return True
    
    # If no expiration date, consider it expired (shouldn't happen with valid membership)
    if not membership_expires:
        return True
    
    try:
        from datetime import datetime
        # Parse the expiration date
        expires_date = datetime.fromisoformat(membership_expires.replace('Z', '+00:00'))
        current_date = datetime.now(expires_date.tzinfo)
        
        # Check if current time is past expiration
        return current_date >= expires_date
        
    except Exception as e:
        debug_log(f"Error checking membership expiration: {e}")
        # If we can't parse the date, consider it expired for safety
        return True