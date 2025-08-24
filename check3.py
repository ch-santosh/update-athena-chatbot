import streamlit as st
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
import qrcode
import io
import base64
import json
from groq import Groq
import re
import os
import sys

# Set page config first to avoid warnings
st.set_page_config(
    page_title="Athena Museum Booking Assistant",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Firebase with enhanced error handling (SILENT MODE)
@st.cache_resource
def init_firebase():
    try:
        if not firebase_admin._apps:
            # Try to use Firebase credentials from Streamlit secrets first
            if "firebase" in st.secrets:
                try:
                    # Get private key and ensure proper formatting
                    private_key = st.secrets["firebase"]["private_key"]
                    
                    # Handle different private key formats
                    if isinstance(private_key, str):
                        # Replace literal \n with actual newlines
                        private_key = private_key.replace('\\n', '\n')
                        
                        # Ensure proper PEM format
                        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                            # If key doesn't have headers, add them
                            private_key = f"-----BEGIN PRIVATE KEY-----\n{private_key}\n-----END PRIVATE KEY-----\n"
                    
                    firebase_config = {
                        "type": st.secrets["firebase"]["type"],
                        "project_id": st.secrets["firebase"]["project_id"],
                        "private_key_id": st.secrets["firebase"]["private_key_id"],
                        "private_key": private_key,
                        "client_email": st.secrets["firebase"]["client_email"],
                        "client_id": st.secrets["firebase"]["client_id"],
                        "auth_uri": st.secrets["firebase"]["auth_uri"],
                        "token_uri": st.secrets["firebase"]["token_uri"],
                        "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
                        "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"],
                        "universe_domain": st.secrets["firebase"]["universe_domain"]
                    }
                    cred = credentials.Certificate(firebase_config)
                except Exception as secrets_error:
                    st.error(f"Failed to load from secrets: {secrets_error}")
                    return None
            else:
                # Fallback to local file for development
                if os.path.exists('firebase_auth.json'):
                    try:
                        # Read and validate the JSON file
                        with open('firebase_auth.json', 'r') as f:
                            firebase_config = json.load(f)
                        
                        # Ensure private key is properly formatted
                        if 'private_key' in firebase_config:
                            private_key = firebase_config['private_key']
                            if isinstance(private_key, str):
                                # Replace literal \n with actual newlines
                                private_key = private_key.replace('\\n', '\n')
                                firebase_config['private_key'] = private_key
                        
                        cred = credentials.Certificate(firebase_config)
                    except json.JSONDecodeError as json_error:
                        st.error(f"Invalid JSON in firebase_auth.json: {json_error}")
                        return None
                    except Exception as file_error:
                        st.error(f"Error reading firebase_auth.json: {file_error}")
                        return None
                else:
                    st.error("❌ Firebase configuration not found!")
                    st.info("Please add Firebase credentials to .streamlit/secrets.toml or create firebase_auth.json file")
                    return None
            
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Firebase initialization failed: {e}")
        st.info("Please check your Firebase configuration and try again.")
        return None

# Initialize Groq client with FIXED API KEY handling
@st.cache_resource
def init_groq():
    try:
        # Use the new API key directly - no caching issues
        api_key = "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"
        
        # Create Groq client with proper error handling
        client = Groq(api_key=api_key)
        
        # Test the connection with a simple call
        test_response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5
        )
        
        return client
    except Exception as e:
        st.error(f"Failed to initialize Groq client: {e}")
        # Return None but don't crash the app
        return None

# Initialize clients
db = init_firebase()
client = init_groq()
MODEL = 'llama3-8b-8192'

# SMTP Configuration - Use secrets if available
try:
    if "SMTP_SERVER" in st.secrets:
        SMTP_SERVER = st.secrets["SMTP_SERVER"]
        SMTP_PORT = int(st.secrets["SMTP_PORT"])
        SMTP_USERNAME = st.secrets["SMTP_USERNAME"]
        SMTP_PASSWORD = st.secrets["SMTP_PASSWORD"]
    else:
        # Fallback for development
        SMTP_SERVER = "smtp.gmail.com"
        SMTP_PORT = 587
        SMTP_USERNAME = "chsantosh2004@gmail.com"
        SMTP_PASSWORD = "kzka uohw hbxg gwgi"
except Exception as e:
    st.error(f"SMTP configuration error: {e}")
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    SMTP_USERNAME = ""
    SMTP_PASSWORD = ""

# Flask app URL
FLASK_APP_URL = "https://my-ticket-tau.vercel.app"

# Museum information
MUSEUM_INFO = {
    "name": "Athena Museum of Science and Technology",
    "address": "123 Science Avenue, Mumbai, Maharashtra 400001, India",
    "hours": {
        "monday_to_saturday": "9:00 AM - 5:00 PM",
        "sunday": "10:00 AM - 4:00 PM",
        "holidays": "Closed on major holidays"
    },
    "ticket_prices": {
        "adult": 500,
        "child": 250,
        "student": 350,
        "senior": 350,
        "family_pack": 1200
    },
    "exhibitions": [
        {
            "name": "AI Revolution",
            "description": "Explore the future of artificial intelligence and its impact on society.",
            "duration": "Until December 31, 2024"
        },
        {
            "name": "Space Odyssey", 
            "description": "Journey through the cosmos and discover the wonders of our universe.",
            "duration": "Until November 15, 2024"
        },
        {
            "name": "Quantum Realm",
            "description": "Dive into the mysteries of quantum physics and understand the building blocks of reality.",
            "duration": "Until January 30, 2025"
        }
    ]
}

# Initialize session state
def init_session_state():
    if 'initialized' not in st.session_state:
        st.session_state.initialized = True
        st.session_state.messages = [{
            "role": "assistant",
            "content": "👋 Welcome to the Athena Museum Booking Assistant! I can help you with booking tickets, provide information about exhibitions, or answer any questions about the museum. How may I assist you today?"
        }]
        st.session_state.show_booking_form = False
        st.session_state.show_ticket_info = False
        st.session_state.booking_data = {}
        st.session_state.last_booking_id = ""
        st.session_state.processing = False
        st.session_state.booking_created = False
        st.session_state.current_booking = None
        st.session_state.displayed_booking = None

# Enhanced CSS with better device compatibility
def load_optimized_css():
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Reset and base styles for better compatibility */
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    
    .stApp {
        opacity: 1 !important;
        transition: none !important;
        background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #16213e 100%) !important;
        min-height: 100vh;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif !important;
    }
    
    /* CSS Variables for better compatibility */
    :root {
        --primary-color: #667eea;
        --secondary-color: #764ba2;
        --accent-color: #4facfe;
        --success-color: #00d4aa;
        --error-color: #ff6b6b;
        --warning-color: #feca57;
        --text-primary: #ffffff;
        --text-secondary: #b8c6db;
        --bg-card: rgba(255, 255, 255, 0.08);
        --border-color: rgba(103, 126, 234, 0.3);
        --shadow-light: 0 4px 15px rgba(0, 0, 0, 0.1);
        --shadow-medium: 0 8px 25px rgba(0, 0, 0, 0.2);
        --shadow-heavy: 0 12px 35px rgba(0, 0, 0, 0.3);
    }
    
    /* Improved typography for all devices */
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif !important;
        color: var(--text-primary) !important;
        background: transparent !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        text-rendering: optimizeLegibility;
    }
    
    /* Enhanced title with better visibility */
    .main-title {
        font-size: clamp(1.8rem, 4vw, 3.5rem);
        font-weight: 700;
        text-align: center;
        margin: 1.5rem 0;
        background: linear-gradient(45deg, #667eea, #764ba2, #4facfe, #00f2fe);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: gradientShift 6s ease infinite;
        line-height: 1.2;
        letter-spacing: -0.02em;
        /* Fallback for devices that don't support background-clip */
        color: #667eea;
    }
    
    @keyframes gradientShift {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    
    .subtitle {
        font-size: clamp(0.9rem, 2.5vw, 1.2rem);
        text-align: center;
        margin-bottom: 2rem;
        color: var(--text-secondary);
        font-weight: 400;
        letter-spacing: 0.5px;
        line-height: 1.4;
    }
    
    /* Improved chat container with better contrast */
    .chat-container {
        max-height: 500px;
        overflow-y: auto;
        padding: 1rem;
        background: var(--bg-card);
        border-radius: 16px;
        border: 1px solid var(--border-color);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        margin-bottom: 1.5rem;
        box-shadow: var(--shadow-medium);
        /* Improved scrollbar for webkit browsers */
        scrollbar-width: thin;
        scrollbar-color: var(--primary-color) transparent;
    }
    
    .chat-container::-webkit-scrollbar {
        width: 6px;
    }
    
    .chat-container::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .chat-container::-webkit-scrollbar-thumb {
        background: var(--primary-color);
        border-radius: 3px;
    }
    
    /* Enhanced chat messages with better readability */
    .chat-message {
        padding: 1rem 1.2rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        display: flex;
        align-items: flex-start;
        gap: 0.8rem;
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        transition: all 0.2s ease;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }
    
    .chat-message.user {
        background: rgba(102, 126, 234, 0.15);
        border-left: 3px solid var(--primary-color);
        margin-left: 1rem;
    }
    
    .chat-message.assistant {
        background: rgba(79, 172, 254, 0.12);
        border-left: 3px solid var(--accent-color);
        margin-right: 1rem;
    }
    
    /* Improved avatars */
    .avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 600;
        font-size: 1rem;
        flex-shrink: 0;
        box-shadow: var(--shadow-light);
    }
    
    .avatar.user {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
        color: white;
    }
    
    .avatar.assistant {
        background: linear-gradient(135deg, var(--accent-color), #00f2fe);
        color: white;
    }
    
    /* Better message content styling */
    .message-content {
        flex-grow: 1;
        line-height: 1.5;
        font-size: 0.95rem;
        color: var(--text-primary);
        font-weight: 400;
    }
    
    /* Enhanced form styling */
    .booking-form {
        background: var(--bg-card);
        border-radius: 16px;
        padding: 1.5rem;
        border: 1px solid var(--border-color);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        box-shadow: var(--shadow-medium);
        margin: 1.5rem 0;
    }
    
    /* Improved input styling for better visibility */
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        background: rgba(255, 255, 255, 0.12) !important;
        border: 2px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 10px !important;
        color: var(--text-primary) !important;
        padding: 0.8rem 1rem !important;
        font-size: 0.95rem !important;
        font-weight: 400 !important;
        transition: all 0.2s ease !important;
        font-family: inherit !important;
    }
    
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus {
        border-color: var(--primary-color) !important;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.2) !important;
        background: rgba(255, 255, 255, 0.18) !important;
        outline: none !important;
    }
    
    .stTextInput > div > div > input::placeholder,
    .stNumberInput > div > div > input::placeholder {
        color: rgba(255, 255, 255, 0.5) !important;
        font-weight: 400 !important;
    }
    
    /* Enhanced button styling */
    .stButton > button {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color)) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.8rem 1.5rem !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        transition: all 0.2s ease !important;
        box-shadow: var(--shadow-light) !important;
        font-family: inherit !important;
        cursor: pointer !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: var(--shadow-medium) !important;
        background: linear-gradient(135deg, var(--secondary-color), var(--primary-color)) !important;
    }
    
    .stButton > button:active {
        transform: translateY(0) !important;
    }
    
    /* Improved alert messages */
    .success-message {
        background: rgba(0, 212, 170, 0.15);
        border: 2px solid var(--success-color);
        border-radius: 12px;
        padding: 1.2rem;
        margin: 1rem 0;
        color: var(--success-color);
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        font-weight: 500;
    }
    
    .error-message {
        background: rgba(255, 107, 107, 0.15);
        border: 2px solid var(--error-color);
        border-radius: 12px;
        padding: 1.2rem;
        margin: 1rem 0;
        color: var(--error-color);
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        font-weight: 500;
    }
    
    /* Enhanced ticket display */
    .ticket-display {
        background: var(--bg-card);
        border-radius: 16px;
        padding: 1.5rem;
        border: 2px solid var(--border-color);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        margin: 1.5rem 0;
        position: relative;
        overflow: hidden;
        box-shadow: var(--shadow-medium);
    }
    
    .ticket-header {
        text-align: center;
        margin-bottom: 1.5rem;
    }
    
    .ticket-header h2 {
        color: var(--primary-color);
        font-size: 1.5rem;
        margin-bottom: 0.5rem;
        font-weight: 600;
    }
    
    .ticket-detail {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.8rem 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        font-size: 0.9rem;
    }
    
    .ticket-detail:last-child {
        border-bottom: none;
    }
    
    .ticket-label {
        font-weight: 500;
        color: var(--text-secondary);
    }
    
    .ticket-value {
        font-weight: 600;
        color: var(--text-primary);
        text-align: right;
        word-break: break-word;
    }
    
    /* QR container improvements */
    .qr-container {
        text-align: center;
        background: var(--bg-card);
        border-radius: 16px;
        padding: 1.5rem;
        margin: 1.5rem 0;
        border: 1px solid var(--border-color);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        box-shadow: var(--shadow-medium);
    }
    
    .qr-code-img {
        max-width: 180px;
        border-radius: 8px;
        background: white;
        padding: 8px;
        margin: 1rem auto;
        display: block;
        box-shadow: var(--shadow-light);
    }
    
    /* Enhanced payment link */
    .payment-link {
        display: block;
        background: linear-gradient(135deg, #f093fb, #f5576c);
        color: white !important;
        text-decoration: none;
        padding: 1rem 1.5rem;
        border-radius: 12px;
        font-weight: 600;
        margin: 1rem 0;
        transition: all 0.2s ease;
        box-shadow: var(--shadow-light);
        text-align: center;
        font-size: 0.95rem;
    }
    
    .payment-link:hover {
        transform: translateY(-2px);
        box-shadow: var(--shadow-medium);
        text-decoration: none;
        color: white !important;
        background: linear-gradient(135deg, #f5576c, #f093fb);
    }
    
    /* Hide Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    
    /* Enhanced mobile responsiveness */
    @media (max-width: 768px) {
        .main-title {
            font-size: 2rem;
            margin: 1rem 0;
        }
        
        .subtitle {
            font-size: 1rem;
            margin-bottom: 1.5rem;
        }
        
        .chat-container {
            max-height: 400px;
            padding: 0.8rem;
        }
        
        .chat-message {
            padding: 0.8rem 1rem;
            margin-bottom: 0.8rem;
            font-size: 0.9rem;
        }
        
        .chat-message.user {
            margin-left: 0;
        }
        
        .chat-message.assistant {
            margin-right: 0;
        }
        
        .booking-form {
            padding: 1.2rem;
        }
        
        .avatar {
            width: 32px;
            height: 32px;
            font-size: 0.9rem;
        }
        
        .ticket-detail {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.3rem;
            padding: 0.6rem 0;
        }
        
        .ticket-value {
            text-align: left;
        }
    }
    
    /* Extra small devices */
    @media (max-width: 480px) {
        .main-title {
            font-size: 1.8rem;
        }
        
        .chat-container {
            max-height: 350px;
            padding: 0.6rem;
        }
        
        .booking-form {
            padding: 1rem;
        }
        
        .stButton > button {
            padding: 0.7rem 1.2rem !important;
            font-size: 0.9rem !important;
        }
    }
    
    /* High contrast mode support */
    @media (prefers-contrast: high) {
        :root {
            --bg-card: rgba(255, 255, 255, 0.15);
            --border-color: rgba(255, 255, 255, 0.5);
            --text-primary: #ffffff;
            --text-secondary: #e0e0e0;
        }
    }
    
    /* Reduced motion support */
    @media (prefers-reduced-motion: reduce) {
        * {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }
    }
    </style>
    """

# Cleanup function for expired bookings
def cleanup_expired_bookings():
    """Clean up expired bookings from Firebase"""
    try:
        if not db:
            return
        
        current_time = datetime.now()
        bookings_ref = db.collection('bookings')
        bookings = bookings_ref.get()
        
        deleted_count = 0
        for booking_doc in bookings:
            booking_data = booking_doc.to_dict()
            validity_date = booking_data.get('validity')
            
            if validity_date:
                if hasattr(validity_date, 'replace'):
                    validity_datetime = validity_date.replace(tzinfo=None)
                else:
                    validity_datetime = validity_date
                
                if validity_datetime <= current_time:
                    booking_doc.reference.delete()
                    
                    email = booking_data.get('email', '')
                    if email:
                        phone_clean = re.sub(r'[^\d+]', '', booking_data.get('phone', ''))
                        if phone_clean:
                            phone_doc_id = f"phone_{phone_clean}"
                            try:
                                db.collection('phone_index').document(phone_doc_id).delete()
                            except:
                                pass
                    
                    deleted_count += 1
        
        if deleted_count > 0:
            st.success(f"🧹 Cleaned up {deleted_count} expired booking(s)")
            
    except Exception as e:
        st.error(f"Cleanup error: {str(e)}")

# Helper function to detect identifier type
def detect_identifier_type(text):
    """Detect if text contains booking ID, email, or phone number"""
    text = text.strip()
    
    if '@' in text and '.' in text:
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        if email_match:
            return "email", email_match.group()
    
    booking_id_match = re.search(r'\bATH\d+\b', text, re.IGNORECASE)
    if booking_id_match:
        return "booking_id", booking_id_match.group().upper()
    
    phone_patterns = [
        r'\+91[\s-]?\d{10}',
        r'\b91\d{10}\b',
        r'\b\d{10}\b',
        r'\+\d{1,3}[\s-]?\d{8,12}',
    ]
    
    for pattern in phone_patterns:
        phone_match = re.search(pattern, text)
        if phone_match:
            return "phone", phone_match.group()
    
    return None, None

# Email sending function
def send_email_confirmation(email, booking_details):
    try:
        if not SMTP_USERNAME or not SMTP_PASSWORD:
            st.warning("Email configuration not available")
            return False
            
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = email
        msg['Subject'] = "Athena Museum Booking Confirmation"
        
        payment_url = f"{FLASK_APP_URL}?email={email}"
        
        body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Inter', sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 30px; background: #f8f9fa; }}
                .footer {{ background: #e9ecef; padding: 20px; text-align: center; font-size: 14px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 15px 30px; text-decoration: none; border-radius: 25px; font-weight: bold; margin: 20px 0; }}
                .details {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #667eea; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🏛️ Athena Museum</h1>
                    <h2>Booking Confirmation</h2>
                </div>
                <div class="content">
                    <p>Dear Visitor,</p>
                    <p>Thank you for choosing the Athena Museum of Science and Technology! Your booking has been created successfully.</p>
                    
                    <div class="details">
                        <h3>📋 Booking Details</h3>
                        <p><strong>Email:</strong> {email}</p>
                        <p><strong>Phone:</strong> {booking_details['phone_number']}</p>
                        <p><strong>Number of Tickets:</strong> {booking_details['no_of_tickets']}</p>
                        <p><strong>Total Amount:</strong> ₹{booking_details['no_of_tickets'] * 500}</p>
                        <p><strong>Validity:</strong> 1 day from booking time</p>
                    </div>
                    
                    <p>To complete your booking, please click the button below to proceed with payment:</p>
                    <div style="text-align: center;">
                        <a href="{payment_url}" class="button">💳 Complete Payment</a>
                    </div>
                    
                    <p>After successful payment, you will receive your official Booking ID and QR code for museum entry.</p>
                </div>
                <div class="footer">
                    <p><strong>Athena Museum of Science and Technology</strong></p>
                    <p>123 Science Avenue, Mumbai, Maharashtra 400001, India</p>
                    <p>📞 +91 22 1234 5678 | 📧 info@athenamuseum.com</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        st.error(f"Failed to send email: {str(e)}")
        return False

# Enhanced Firebase booking function
def create_booking(email, phone, tickets):
    try:
        if not db:
            return {"error": "Database connection failed"}
        
        cleanup_expired_bookings()
        
        email_doc_id = email.replace('.', '_').replace('@', '_at_')
        
        try:
            existing_doc = db.collection('bookings').document(email_doc_id).get()
            if existing_doc.exists:
                existing_data = existing_doc.to_dict()
                
                validity_date = existing_data.get('validity')
                if validity_date:
                    if hasattr(validity_date, 'replace'):
                        validity_datetime = validity_date.replace(tzinfo=None)
                    else:
                        validity_datetime = validity_date
                    
                    if validity_datetime <= datetime.now():
                        existing_doc.reference.delete()
                        phone_clean = re.sub(r'[^\d+]', '', phone)
                        if phone_clean:
                            phone_doc_id = f"phone_{phone_clean}"
                            try:
                                db.collection('phone_index').document(phone_doc_id).delete()
                            except:
                                pass
                    else:
                        if existing_data.get('status') == 'pending':
                            return {
                                "success": True,
                                "booking_id": existing_data.get('booking_id', 'Pending'),
                                "amount": existing_data.get('amount', tickets * 500),
                                "payment_url": f"{FLASK_APP_URL}?email={email}",
                                "existing": True
                            }
        except Exception as e:
            st.write(f"No existing booking found: {e}")
        
        amount = tickets * 500
        booking_time = datetime.now()
        validity_time = booking_time + timedelta(days=1)
        
        booking_data = {
            "email": email,
            "phone": phone,
            "tickets": tickets,
            "amount": amount,
            "status": "pending",
            "created_at": booking_time,
            "validity": validity_time,
            "booking_id": None,
            "hash": None,
            "updated_at": booking_time,
            "doc_id": email_doc_id
        }
        
        db.collection('bookings').document(email_doc_id).set(booking_data)
        
        if phone:
            phone_clean = re.sub(r'[^\d+]', '', phone)
            phone_doc_id = f"phone_{phone_clean}"
            phone_index_data = {
                "phone": phone,
                "email": email,
                "doc_id": email_doc_id,
                "created_at": booking_time
            }
            db.collection('phone_index').document(phone_doc_id).set(phone_index_data)
        
        booking_details = {
            "phone_number": phone,
            "no_of_tickets": tickets
        }
        email_sent = send_email_confirmation(email, booking_details)
        
        return {
            "success": True,
            "doc_id": email_doc_id,
            "amount": amount,
            "payment_url": f"{FLASK_APP_URL}?email={email}",
            "email_sent": email_sent
        }
        
    except Exception as e:
        st.error(f"Booking creation error: {str(e)}")
        return {"error": f"Booking failed: {str(e)}"}

# Get booking information function
def get_booking_info(identifier):
    try:
        if not db:
            return {"error": "Database connection failed"}
        
        cleanup_expired_bookings()
        
        booking_doc = None
        
        if '@' in identifier:
            email_doc_id = identifier.replace('.', '_').replace('@', '_at_')
            try:
                booking_doc = db.collection('bookings').document(email_doc_id).get()
                if not booking_doc.exists:
                    return {"error": f"No booking found for email: {identifier}"}
            except Exception as e:
                return {"error": f"Error searching by email: {str(e)}"}
        
        elif identifier.upper().startswith('ATH'):
            try:
                bookings = db.collection('bookings').where('booking_id', '==', identifier.upper()).limit(1).get()
                if bookings:
                    booking_doc = bookings[0]
                else:
                    return {"error": f"No booking found with ID: {identifier}"}
            except Exception as e:
                return {"error": f"Error searching by booking ID: {str(e)}"}
        
        elif any(char.isdigit() for char in identifier):
            try:
                clean_phone = re.sub(r'[^\d+]', '', identifier)
                possible_phones = [
                    clean_phone,
                    clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone,
                    f"91{clean_phone[-10:]}" if len(clean_phone) >= 10 else clean_phone
                ]
                
                email_found = None
                for phone_format in possible_phones:
                    phone_doc_id = f"phone_{phone_format}"
                    try:
                        phone_doc = db.collection('phone_index').document(phone_doc_id).get()
                        if phone_doc.exists:
                            email_found = phone_doc.to_dict().get('email')
                            break
                    except:
                        continue
                
                if email_found:
                    email_doc_id = email_found.replace('.', '_').replace('@', '_at_')
                    booking_doc = db.collection('bookings').document(email_doc_id).get()
                    if not booking_doc.exists:
                        return {"error": f"Booking data inconsistency for phone: {identifier}"}
                else:
                    return {"error": f"No booking found for phone: {identifier}"}
            except Exception as e:
                return {"error": f"Error searching by phone: {str(e)}"}
        
        else:
            return {"error": f"Invalid identifier format: {identifier}"}
        
        if not booking_doc or not booking_doc.exists:
            return {"error": f"No booking found for: {identifier}"}
        
        booking_data = booking_doc.to_dict()
        
        validity_date = booking_data.get('validity')
        current_time = datetime.now()
        
        if validity_date:
            if hasattr(validity_date, 'replace'):
                validity_datetime = validity_date.replace(tzinfo=None)
            else:
                validity_datetime = validity_date
            
            is_valid = validity_datetime > current_time
            validity_str = validity_datetime.strftime('%d %b %Y, %H:%M')
            
            if is_valid:
                time_remaining = validity_datetime - current_time
                hours_remaining = int(time_remaining.total_seconds() // 3600)
                minutes_remaining = int((time_remaining.total_seconds() % 3600) // 60)
                validity_str += f" ({hours_remaining}h {minutes_remaining}m remaining)"
            else:
                validity_str += " (EXPIRED)"
        else:
            is_valid = False
            validity_str = "Not set"
        
        return {
            "success": True,
            "booking_id": booking_data.get('booking_id', 'Pending Payment'),
            "email": booking_data.get('email'),
            "phone": booking_data.get('phone'),
            "tickets": booking_data.get('tickets'),
            "amount": booking_data.get('amount'),
            "status": booking_data.get('status', 'pending'),
            "validity": validity_date,
            "validity_str": validity_str,
            "is_valid": is_valid,
            "hash": booking_data.get('hash', ''),
            "created_at": booking_data.get('created_at')
        }
        
    except Exception as e:
        st.error(f"Database query error: {str(e)}")
        return {"error": f"Failed to retrieve booking: {str(e)}"}

# Generate QR code
def generate_qr_code(booking_id, hash_code):
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr_data = f"ATHENA-MUSEUM-{booking_id}-{hash_code}"
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return img_str
    except Exception as e:
        st.error(f"QR code generation failed: {str(e)}")
        return None

# FIXED Chat with AI function - No more authentication issues
def chat_with_ai(messages):
    try:
        # If client is None, provide fallback responses
        if not client:
            return get_fallback_response(messages[-1]["content"] if messages else "")
            
        system_message = {
            "role": "system",
            "content": """You are EaseEntry AI, the official assistant for the Athena Museum of Science and Technology. 

Museum Information:
- Name: Athena Museum of Science and Technology
- Address: 123 Science Avenue, Mumbai, Maharashtra 400001, India
- Hours: Monday-Saturday 9AM-5PM, Sunday 10AM-4PM
- Ticket Price: ₹500 per person
- Current Exhibitions: AI Revolution, Space Odyssey, Quantum Realm

Your main functions:
1. Help users book tickets (collect email, phone, number of tickets)
2. Provide museum information
3. Help users check their booking status
4. Answer general questions about the museum

Be friendly, helpful, and enthusiastic. Keep responses concise but informative.
If users want to book tickets, guide them to provide their email, phone number, and number of tickets.
If users want to check bookings, ask for their booking ID, email address, or phone number."""
        }
        
        api_messages = [system_message] + messages
        
        # Make the API call with proper error handling
        response = client.chat.completions.create(
            model=MODEL,
            messages=api_messages,
            temperature=0.7,
            max_tokens=1000,
            timeout=30  # Add timeout
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        # Provide helpful fallback responses instead of error messages
        return get_fallback_response(messages[-1]["content"] if messages else "")

def get_fallback_response(user_message):
    """Provide fallback responses when AI is unavailable"""
    user_message = user_message.lower()
    
    # Booking related queries
    if any(word in user_message for word in ["book", "ticket", "reserve", "buy", "purchase"]):
        return "I'd be happy to help you book tickets! Please use the booking form that will appear below to provide your email, phone number, and number of tickets needed."
    
    # Museum information queries
    elif any(word in user_message for word in ["hours", "time", "open", "close"]):
        return "🕒 **Museum Hours:**\n- Monday to Saturday: 9:00 AM - 5:00 PM\n- Sunday: 10:00 AM - 4:00 PM\n- Closed on major holidays"
    
    elif any(word in user_message for word in ["price", "cost", "ticket", "fee"]):
        return "🎫 **Ticket Prices:**\n- Adult: ₹500 per person\n- Child: ₹250 per person\n- Student: ₹350 per person\n- Senior: ₹350 per person\n- Family Pack: ₹1200"
    
    elif any(word in user_message for word in ["location", "address", "where"]):
        return "📍 **Location:**\nAthena Museum of Science and Technology\n123 Science Avenue, Mumbai, Maharashtra 400001, India"
    
    elif any(word in user_message for word in ["exhibition", "show", "display"]):
        return "🎨 **Current Exhibitions:**\n• **AI Revolution** - Explore the future of artificial intelligence\n• **Space Odyssey** - Journey through the cosmos\n• **Quantum Realm** - Dive into quantum physics mysteries"
    
    # Booking status queries
    elif any(word in user_message for word in ["check", "status", "booking", "find"]):
        return "I can help you check your booking status! Please use the booking check form that will appear below, or simply provide your booking ID, email address, or phone number."
    
    # Greetings
    elif any(word in user_message for word in ["hello", "hi", "hey", "greetings"]):
        return "Hello! 👋 Welcome to the Athena Museum of Science and Technology! I'm here to help you with booking tickets, checking your booking status, or providing information about our museum. How can I assist you today?"
    
    # Default response
    else:
        return "I'm here to help you with the Athena Museum! I can assist you with:\n\n🎫 **Booking tickets**\n🔍 **Checking booking status**\n🏛️ **Museum information** (hours, prices, location)\n🎨 **Exhibition details**\n\nWhat would you like to know?"

# Function to display booking validity
def display_booking_validity(booking_info):
    """Display booking validity information"""
    if booking_info.get("success"):
        booking = booking_info
        
        booking_key = f"{booking['email']}_{booking.get('booking_id', 'pending')}"
        
        if st.session_state.displayed_booking != booking_key:
            st.session_state.displayed_booking = booking_key
        
        if booking['status'] == 'completed':
            if booking['is_valid']:
                status_emoji = "✅"
                status_text = "CONFIRMED & VALID"
                status_color = "#00d4aa"
            else:
                status_emoji = "⚠️"
                status_text = "CONFIRMED BUT EXPIRED"
                status_color = "#feca57"
        elif booking['status'] == 'pending':
            status_emoji = "⏳"
            status_text = "PENDING PAYMENT"
            status_color = "#feca57"
        else:
            status_emoji = "❌"
            status_text = "CANCELLED"
            status_color = "#ff6b6b"
        
        with st.container():
            st.markdown(f"""
            <div class="ticket-display" id="booking-{booking_key}">
                <div class="ticket-header">
                    <h2>{status_emoji} Booking Status</h2>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Booking ID:</span>
                    <span class="ticket-value">{booking['booking_id']}</span>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Email:</span>
                    <span class="ticket-value">{booking['email']}</span>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Phone:</span>
                    <span class="ticket-value">{booking['phone']}</span>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Tickets:</span>
                    <span class="ticket-value">{booking['tickets']}</span>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Amount:</span>
                    <span class="ticket-value">₹{booking['amount']}</span>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Status:</span>
                    <span class="ticket-value" style="color: {status_color}; font-weight: bold;">{status_text}</span>
                </div>
                <div class="ticket-detail">
                    <span class="ticket-label">Valid Until:</span>
                    <span class="ticket-value">{booking['validity_str']}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if booking['status'] == 'pending':
                payment_url = f"{FLASK_APP_URL}?email={booking['email']}"
                st.markdown(f"""
                <div style="text-align: center; margin: 1rem 0;">
                    <a href="{payment_url}" target="_blank" class="payment-link">
                        💳 Complete Payment Now
                    </a>
                </div>
                """, unsafe_allow_html=True)
            
            if booking['status'] == 'completed' and booking.get('hash') and booking['is_valid']:
                qr_code = generate_qr_code(booking['booking_id'], booking['hash'])
                if qr_code:
                    st.markdown(f"""
                    <div class="qr-container">
                        <h3>📱 Your QR Code</h3>
                        <img src="data:image/png;base64,{qr_code}" alt="QR Code" class="qr-code-img">
                        <p>Present this QR code at the museum entrance</p>
                        <p><strong>Security Hash:</strong> {booking['hash']}</p>
                    </div>
                    """, unsafe_allow_html=True)
        
        return True
    else:
        st.markdown(f"""
        <div class="error-message">
            <h3>❌ Booking Not Found</h3>
            <p>{booking_info.get('error', 'No booking found with that information')}</p>
        </div>
        """, unsafe_allow_html=True)
        return False

# Main application
def main():
    init_session_state()
    
    st.markdown(load_optimized_css(), unsafe_allow_html=True)
    
    st.markdown('<h1 class="main-title">🏛️ Athena Museum</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">AI-Powered Booking Assistant</p>', unsafe_allow_html=True)
    
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    
    for message in st.session_state.messages:
        if message["role"] == "user":
            st.markdown(f"""
            <div class="chat-message user">
                <div class="avatar user">👤</div>
                <div class="message-content">{message["content"]}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="chat-message assistant">
                <div class="avatar assistant">🤖</div>
                <div class="message-content">{message["content"]}</div>
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    if st.session_state.booking_created and st.session_state.current_booking:
        booking = st.session_state.current_booking
        payment_url = booking['payment_url']
        
        st.markdown(f"""
        <div class="success-message">
            <h3>✅ Booking Created Successfully!</h3>
            <p><strong>Amount:</strong> ₹{booking['amount']}</p>
            <p>Your booking has been saved. Please complete your payment to confirm your booking.</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div style="text-align: center; margin: 2rem 0;">
            <a href="{payment_url}" target="_blank" class="payment-link">
                💳 Complete Payment Now - Click Here
            </a>
        </div>
        """, unsafe_allow_html=True)
        
        st.session_state.booking_created = False
        st.session_state.current_booking = None
    
    if st.session_state.show_booking_form:
        st.markdown('<div class="booking-form">', unsafe_allow_html=True)
        st.markdown("### 🎫 Book Your Tickets")
        
        with st.form("booking_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                email = st.text_input("📧 Email Address", placeholder="your.email@example.com")
                tickets = st.number_input("🎫 Number of Tickets", min_value=1, max_value=10, value=1)
            with col2:
                phone = st.text_input("📱 Phone Number", placeholder="+91 XXXXXXXXXX")
                st.markdown(f"**Total Amount: ₹{tickets * 500}**")
            
            submitted = st.form_submit_button("🚀 Book Now", use_container_width=True)
            
            if submitted:
                if email and phone and tickets:
                    if not st.session_state.processing:
                        st.session_state.processing = True
                        
                        with st.spinner("Creating your booking..."):
                            result = create_booking(email, phone, tickets)
                        
                        if result.get("success"):
                            st.session_state.current_booking = result
                            st.session_state.booking_created = True
                            
                            if result.get("existing"):
                                chat_message = f"I found an existing pending booking for your email. Please complete your payment for ₹{result['amount']}."
                            else:
                                chat_message = f"Great! I've created your booking for ₹{result['amount']}. Please complete your payment using the link that will open automatically."
                            
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": chat_message
                            })
                            
                            st.session_state.show_booking_form = False
                            st.session_state.processing = False
                            st.rerun()
                        else:
                            st.markdown(f"""
                            <div class="error-message">
                                <h3>❌ Booking Failed</h3>
                                <p>{result.get('error', 'Unknown error occurred')}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            st.session_state.processing = False
                else:
                    st.error("Please fill in all required fields.")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    if st.session_state.show_ticket_info:
        st.markdown('<div class="booking-form">', unsafe_allow_html=True)
        st.markdown("### 🔍 Check Your Booking")
        
        with st.form("ticket_info_form", clear_on_submit=True):
            identifier = st.text_input("🎫 Booking ID, 📧 Email, or 📱 Phone Number", 
                                     placeholder="Enter your booking ID, email, or phone number")
            submitted = st.form_submit_button("🔍 Check Booking", use_container_width=True)
            
            if submitted and identifier:
                with st.spinner("Retrieving your booking..."):
                    result = get_booking_info(identifier)
                
                if result.get("success"):
                    display_booking_validity(result)
                    
                    booking = result
                    validity_status = "valid" if booking['is_valid'] else "expired"
                    status_text = f"{booking['status']} and {validity_status}" if booking['status'] == 'completed' else booking['status']
                    
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"Found your booking! ID: {booking['booking_id']}, {booking['tickets']} tickets for ₹{booking['amount']}. Status: {status_text}."
                    })
                    
                    st.session_state.show_ticket_info = False
                    st.rerun()
                else:
                    st.markdown(f"""
                    <div class="error-message">
                        <h3>❌ Booking Not Found</h3>
                        <p>{result.get('error', 'No booking found with that information')}</p>
                        <p>Please check your booking ID, email, or phone number and try again.</p>
                    </div>
                    """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    user_input = st.chat_input("💬 Type your message here...")
    
    if user_input and not st.session_state.processing:
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        identifier_type, identifier_value = detect_identifier_type(user_input)
        
        if identifier_type and identifier_value:
            with st.spinner("Checking your booking..."):
                result = get_booking_info(identifier_value)
            
            if result.get("success"):
                display_booking_validity(result)
                
                booking = result
                validity_status = "valid" if booking['is_valid'] else "expired"
                if booking['status'] == 'completed':
                    status_text = f"confirmed and {validity_status}"
                else:
                    status_text = booking['status']
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Found your booking! ID: {booking['booking_id']}, {booking['tickets']} tickets for ₹{booking['amount']}. Status: {status_text}."
                })
            else:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"❌ {result.get('error', f'No booking found with {identifier_value}')}"
                })
            
            st.rerun()
        
        elif any(keyword in user_input.lower() for keyword in ["book", "ticket", "reserve", "buy", "purchase"]):
            st.session_state.show_booking_form = True
            st.session_state.messages.append({
                "role": "assistant",
                "content": "I'd be happy to help you book tickets! Please fill out the form below:"
            })
            st.rerun()
        
        elif any(keyword in user_input.lower() for keyword in ["check", "status", "booking", "my booking", "ticket info", "find"]):
            st.session_state.show_ticket_info = True
            st.session_state.messages.append({
                "role": "assistant",
                "content": "I can help you check your booking status. Please enter your booking ID, email address, or phone number:"
            })
            st.rerun()
        
        else:
            with st.spinner("Thinking..."):
                ai_response = chat_with_ai(st.session_state.messages)
            
            st.session_state.messages.append({
                "role": "assistant",
                "content": ai_response
            })
            st.rerun()
    
    with st.sidebar:
        st.markdown("### 🏛️ Museum Information")
        st.markdown(f"""
        **📍 Address:**  
        {MUSEUM_INFO['address']}
        
        **🕒 Hours:**  
        Mon-Sat: {MUSEUM_INFO['hours']['monday_to_saturday']}  
        Sunday: {MUSEUM_INFO['hours']['sunday']}
        
        **🎫 Ticket Price:**  
        ₹{MUSEUM_INFO['ticket_prices']['adult']} per person
        
        **🎨 Current Exhibitions:**
        """)
        
        for exhibition in MUSEUM_INFO['exhibitions']:
            st.markdown(f"• **{exhibition['name']}** - {exhibition['description']}")
        
        if st.button("🧹 Clean Expired Bookings"):
            cleanup_expired_bookings()

if __name__ == "__main__":
    main()
