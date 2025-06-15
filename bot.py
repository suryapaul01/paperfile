from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, LabeledPrice, ChatMember
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, PreCheckoutQueryHandler
from telegram.error import Conflict, NetworkError, TelegramError
from functools import wraps
from telegram.constants import ParseMode
import asyncio
import signal
import sys
from firebase_config import initialize_firebase, upload_file_to_firebase, download_file_from_firebase
import tempfile
import os
import atexit
from pathlib import Path

from config import TOKEN, ADMIN_IDS
from database import init_db, SessionLocal, User, QuestionPaper

# List of required channel usernames (to be filled by admin)
REQUIRED_CHANNELS = []

# Initialize Firebase
bucket = initialize_firebase()

# --- Database Utility Functions ---
async def get_or_create_user(telegram_id: int, db):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, stars=0) # New users start with 0 stars
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

# --- Channel Subscription Check ---
async def check_channel_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not REQUIRED_CHANNELS:
        return True
    
    user_id = update.effective_user.id
    not_subscribed = []
    
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                not_subscribed.append(channel)
        except Exception as e:
            print(f"Error checking subscription for channel {channel}: {e}")
            not_subscribed.append(channel)
    
    if not_subscribed:
        channels_text = "\n".join([f"• @{channel.replace('@', '')}" for channel in not_subscribed])
        message = (
            "⚠️ <b>Please subscribe to our channels first:</b>\n\n"
            f"{channels_text}\n\n"
            "After subscribing, click the button below to continue."
        )
        keyboard = [[InlineKeyboardButton("I've Subscribed ✅", callback_data="check_subscription")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return False
    return True

# --- Decorators ---
def require_subscription(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        is_subscribed = await check_channel_subscription(update, context)
        if is_subscribed:
            return await func(update, context, *args, **kwargs)
        return None
    return wrapper

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if str(user_id) not in ADMIN_IDS:
            await update.message.reply_text("⚠️ This command is only available for admins.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Error Handlers ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors caused by updates."""
    if isinstance(context.error, Conflict):
        print("Error: Bot instance is already running elsewhere. Shutting down...")
        await context.application.stop()
        sys.exit(1)
    elif isinstance(context.error, NetworkError):
        print("Network error occurred. Waiting before retry...")
        await asyncio.sleep(1)
    else:
        print(f"Error: {str(context.error)}")

# --- Signal Handlers ---
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    print("Received shutdown signal. Cleaning up...")
    cleanup()
    sys.exit(0)

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_subscribed = await check_channel_subscription(update, context)
    if not is_subscribed:
        return

    db = SessionLocal()
    user = await get_or_create_user(update.effective_user.id, db)
    db.close()
    welcome_message = (
        "Hello! 👋 Welcome to the MAKAUT Question Paper Bot!\n\n"
        "Here, you can easily purchase previous year question papers for different departments and semesters of MAKAUT college.\n\n"
        "Each paper costs 5 stars. You can also purchase papers in bulk for a discounted rate!\n\n"
        "You can buy stars in advance using /buy_star <amount> or pay stars directly when purchasing a paper.\n\n"
        "Use the quick buttons below to get started!"
    )
    keyboard = [
        [InlineKeyboardButton("Topup Wallet ⭐", callback_data="topup_wallet"), InlineKeyboardButton("Purchase Questions", callback_data="purchase_questions")],
        [InlineKeyboardButton("Profile", callback_data="profile"), InlineKeyboardButton("About Us", callback_data="about_us")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 <b>Available Commands:</b>\n\n"
        "/start - Start the bot\n"
        "/history - View your purchase history\n"
        "/profile - View your profile\n"
        "/purchase - Start purchasing question papers\n"
        "/buy_star - Buy Telegram Stars\n"
        "/help - Show this help message\n\n"
        "💡 <b>Tips:</b>\n"
        "• Bulk purchases get 10% discount\n"
        "• You can top up your wallet anytime\n"
        "• Use the menu buttons for easy navigation"
    )
    keyboard = [
        [InlineKeyboardButton("Back", callback_data="back_to_main"), InlineKeyboardButton("Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    user_telegram_id = update.effective_user.id
    user_with_papers = db.query(User).filter(User.telegram_id == user_telegram_id).first()
    if user_with_papers:
        db.refresh(user_with_papers)
        if user_with_papers.purchased_papers:
            history_text = "📚 <b>Your Purchase History:</b>\n\n"
            for paper in user_with_papers.purchased_papers:
                history_text += f"• {paper.department} - {paper.semester} - {paper.year} - {paper.paper_name}\n"
        else:
            history_text = "📚 <b>Your Purchase History:</b>\n\nNo purchases yet."
    else:
        history_text = "❌ User not found. Please start the bot with /start first."
    
    keyboard = [
        [InlineKeyboardButton("Back", callback_data="back_to_main"), InlineKeyboardButton("Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(history_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    db.close()

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_profile(update, context, is_command=True)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, is_command=False):
    db = SessionLocal()
    user_telegram_id = update.effective_user.id if is_command else update.callback_query.from_user.id
    user = await get_or_create_user(user_telegram_id, db)
    
    # Get user's purchase history
    purchased_papers = user.purchased_papers
    total_papers = len(purchased_papers)
    
    # Calculate total stars spent
    total_spent = sum(paper.price for paper in purchased_papers)
    
    # Get department-wise statistics
    dept_stats = {}
    for paper in purchased_papers:
        if paper.department not in dept_stats:
            dept_stats[paper.department] = 0
        dept_stats[paper.department] += 1
    
    profile_text = (
        f"👤 <b>User Profile</b>\n\n"
        f"🆔 User ID: <code>{user.telegram_id}</code>\n"
        f"⭐ Stars Balance: <b>{user.stars}</b>\n\n"
        f"📊 <b>Purchase Statistics</b>\n"
        f"📚 Total Papers Purchased: <b>{total_papers}</b>\n"
        f"💰 Total Stars Spent: <b>{total_spent}</b>\n\n"
    )
    
    if dept_stats:
        profile_text += "📈 <b>Department-wise Statistics:</b>\n"
        for dept, count in dept_stats.items():
            profile_text += f"• {dept}: <b>{count}</b> papers\n"
        profile_text += "\n"
    
    profile_text += "📝 <b>Recent Purchases</b>\n"
    # Add recent purchases (last 5)
    recent_papers = purchased_papers[-5:] if purchased_papers else []
    if recent_papers:
        for paper in recent_papers:
            profile_text += f"• {paper.department} - {paper.semester} - {paper.year} - {paper.paper_name}\n"
    else:
        profile_text += "No purchases yet.\n"
    
    keyboard = [
        [InlineKeyboardButton("Back", callback_data="back_to_main"), InlineKeyboardButton("Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if is_command:
        await update.message.reply_text(profile_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.callback_query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    db.close()

async def about_us_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_about_us(update, context, is_command=True)

async def show_about_us(update: Update, context: ContextTypes.DEFAULT_TYPE, is_command=False):
    about_text = (
        "<b>About Us</b>\n\n"
        "🤖 <b>MAKAUT Question Paper Bot</b>\n\n"
        "This bot is designed to help MAKAUT students easily access and purchase previous year question papers.\n\n"
        "📚 <b>Features:</b>\n"
        "• Easy paper browsing by department, semester, and year\n"
        "• Secure payment system using Telegram Stars\n"
        "• Bulk purchase discounts\n"
        "• Instant paper delivery\n"
        "• Purchase history tracking\n\n"
        "💡 <b>Tips:</b>\n"
        "• Use /help to see all available commands\n"
        "• Bulk purchases get 10% discount\n"
        "• You can top up your wallet anytime\n\n"
        "📞 <b>Support:</b>\n"
        "For any issues or queries, contact the admin."
    )
    keyboard = [
        [InlineKeyboardButton("Back", callback_data="back_to_main"), InlineKeyboardButton("Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if is_command:
        await update.message.reply_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.callback_query.edit_message_text(about_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def about_us_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_about_us(update, context, is_command=False)

async def cancel_star_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Clear the waiting state
    if 'waiting_for_star_amount' in context.user_data:
        context.user_data.pop('waiting_for_star_amount')
    
    # Get the previous screen
    previous_screen = context.user_data.get('previous_screen', 'main_menu')
    context.user_data.pop('previous_screen', None)  # Clear the stored screen
    
    if previous_screen == 'main_menu':
        welcome_message = (
            "Hello! 👋 Welcome to the MAKAUT Question Paper Bot!\n\n"
            "Here, you can easily purchase previous year question papers for different departments and semesters of MAKAUT college.\n\n"
            "Each paper costs 5 stars. You can also purchase papers in bulk for a discounted rate!\n\n"
            "You can buy stars in advance using /buy_star <amount> or pay stars directly when purchasing a paper.\n\n"
            "Use the quick buttons below to get started!"
        )
        keyboard = [
            [InlineKeyboardButton("Topup Wallet ⭐", callback_data="topup_wallet"), InlineKeyboardButton("Purchase Questions", callback_data="purchase_questions")],
            [InlineKeyboardButton("Profile", callback_data="profile"), InlineKeyboardButton("About Us", callback_data="about_us")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(welcome_message, reply_markup=reply_markup)
    else:
        # Return to the previous screen
        await query.edit_message_text("Star purchase cancelled.")

# --- Purchase Flow Handlers ---
async def purchase_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please choose a department:", reply_markup=get_department_keyboard())

# --- Helper for 2-column inline keyboards ---
def chunk_buttons(items, prefix):
    buttons = [InlineKeyboardButton(str(item), callback_data=f"{prefix}_{item}") for item in items]
    return [buttons[i:i+2] for i in range(0, len(buttons), 2)]

def error_keyboard(back_callback, menu_callback="main_menu"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data=back_callback), InlineKeyboardButton("Main Menu", callback_data=menu_callback)]
    ])

def get_department_keyboard():
    db = SessionLocal()
    departments = db.query(QuestionPaper.department).filter(QuestionPaper.department != "").distinct().all()
    db.close()
    departments = [d[0] for d in departments if d[0] and not d[0].startswith("__")]
    keyboard = chunk_buttons(departments, "dept")
    keyboard.append([InlineKeyboardButton("Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

async def department_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    department = query.data.split("_")[1]
    context.user_data['department'] = department
    await query.edit_message_text(f"You selected {department}. Now choose a semester:", reply_markup=get_semester_keyboard(department))

def get_semester_keyboard(department):
    db = SessionLocal()
    semesters = db.query(QuestionPaper.semester).filter(
        QuestionPaper.department == department,
        QuestionPaper.semester != ""
    ).distinct().all()
    db.close()
    semesters = [s[0] for s in semesters if s[0]]
    keyboard = chunk_buttons(semesters, "sem")
    keyboard.append([InlineKeyboardButton("Back", callback_data="back_to_dept"), InlineKeyboardButton("Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

async def semester_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    semester = query.data.split("_")[1]
    context.user_data['semester'] = semester
    department = context.user_data.get('department')

    db = SessionLocal()
    available_years = db.query(QuestionPaper.year).filter(
        QuestionPaper.department == department,
        QuestionPaper.semester == semester,
        QuestionPaper.year != ""
    ).distinct().all()
    db.close()

    if available_years:
        keyboard = chunk_buttons([year[0] for year in available_years], "year")
        keyboard.append([InlineKeyboardButton("Back", callback_data="back_to_sem"), InlineKeyboardButton("Main Menu", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"You selected {semester}. Now choose a year for {department} department:", reply_markup=reply_markup)
    else:
        await query.edit_message_text("No years found for this department and semester.", reply_markup=error_keyboard("back_to_sem"))

async def year_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    year = query.data.split("_")[1]
    context.user_data['year'] = year

    department = context.user_data.get('department')
    semester = context.user_data.get('semester')

    db = SessionLocal()
    papers = db.query(QuestionPaper).filter(
        QuestionPaper.department == department,
        QuestionPaper.semester == semester,
        QuestionPaper.year == year,
        ~QuestionPaper.paper_name.in_(["__DEPT__", "__SEM__", "__YEAR__"])
    ).all()
    db.close()

    if papers:
        context.user_data['current_papers'] = {paper.id: paper for paper in papers}
        paper_list = "Available question papers for purchase:\n\n"
        for paper in papers:
            paper_list += f"{paper.paper_name} ({paper.price} stars)\n"
        # 2-column layout
        buttons = [InlineKeyboardButton(paper.paper_name, callback_data=f"select_paper_{paper.id}") for paper in papers]
        keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        keyboard.append([InlineKeyboardButton("Bulk Purchase (10% off)", callback_data="bulk_purchase")])
        keyboard.append([InlineKeyboardButton("Back", callback_data="back_to_year"), InlineKeyboardButton("Main Menu", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(paper_list, reply_markup=reply_markup)
    else:
        await query.edit_message_text("No question papers found for the selected criteria.", reply_markup=error_keyboard("back_to_year"))

async def select_paper_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    paper_id = int(query.data.split("_")[2])

    db = SessionLocal()
    user = await get_or_create_user(update.effective_user.id, db)
    paper = db.query(QuestionPaper).filter(QuestionPaper.id == paper_id).first()

    if not paper:
        await query.edit_message_text("Error: Question paper not found.")
        db.close()
        return

    db.refresh(user)
    if paper in user.purchased_papers:
        await query.edit_message_text(f"You have already purchased {paper.paper_name}. Sending it again.")
        await send_paper_pdf(update, context, paper)
        db.close()
        return

    if user.stars >= paper.price:
        try:
            user.stars -= paper.price
            user.purchased_papers.append(paper)
            db.add(user)
            db.commit()
            db.refresh(user)
            await query.edit_message_text(f"Successfully purchased {paper.paper_name} for {paper.price} stars. Your remaining stars: {user.stars}")
            await send_paper_pdf(update, context, paper)
        except Exception as e:
            db.rollback()
            await query.edit_message_text(f"An error occurred during purchase: {e}")
        db.close()
    else:
        # Not enough stars, generate Telegram Stars invoice
        title = f"Purchase {paper.paper_name}"
        description = f"Purchase {paper.paper_name} for {paper.price} Stars."
        payload = f"single_paper_{paper.id}"
        prices = [LabeledPrice(label=f'{paper.paper_name}', amount=paper.price)]
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=prices,
            is_flexible=False,
        )
        db.close()

async def bulk_purchase_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    department = context.user_data.get('department')
    semester = context.user_data.get('semester')
    year = context.user_data.get('year')

    if not all([department, semester, year]):
        await query.edit_message_text("Error: It seems the department, semester, or year was not selected. Please start over using /purchase.")
        return

    db = SessionLocal()
    user = await get_or_create_user(update.effective_user.id, db)
    db.refresh(user)
    papers_in_year = db.query(QuestionPaper).filter(
        QuestionPaper.department == department,
        QuestionPaper.semester == semester,
        QuestionPaper.year == year
    ).all()

    if not papers_in_year:
        await query.edit_message_text("No papers found for bulk purchase in this year. Please select again using /purchase.")
        db.close()
        return

    papers_to_purchase = [p for p in papers_in_year if p not in user.purchased_papers]
    if not papers_to_purchase:
        await query.edit_message_text("You have already purchased all available papers for this year.")
        db.close()
        return

    total_price = sum(paper.price for paper in papers_to_purchase)
    discounted_price = int(total_price * 0.90) # 10% discount

    if user.stars >= discounted_price:
        try:
            user.stars -= discounted_price
            for paper in papers_to_purchase:
                user.purchased_papers.append(paper)
            db.add(user)
            db.commit()
            db.refresh(user)
            await query.edit_message_text(f"Successfully purchased {len(papers_to_purchase)} papers for {discounted_price} stars (10% discount). Your remaining stars: {user.stars}")
            for paper in papers_to_purchase:
                await send_paper_pdf(update, context, paper)
        except Exception as e:
            db.rollback()
            await query.edit_message_text(f"An error occurred during bulk purchase: {e}")
        db.close()
    else:
        # Not enough stars, generate Telegram Stars invoice for bulk
        title = f"Bulk Purchase: {department} - {semester} - {year} Papers"
        description = f"Purchase {len(papers_to_purchase)} papers for {discounted_price} Stars (10% discount)."
        payload = f"bulk_purchase_{department}_{semester}_{year}"
        prices = [LabeledPrice(label=f'{discounted_price} Stars', amount=discounted_price)]
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=prices,
            is_flexible=False,
        )
        db.close()

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Check if user is in purchase flow
    if any(key in context.user_data for key in ['department', 'semester', 'year']):
        # If in purchase flow, go to department selection
        await query.edit_message_text("Please choose a department:", reply_markup=get_department_keyboard())
    else:
        # Otherwise, go to main menu
        welcome_message = (
            "Hello! 👋 Welcome to the MAKAUT Question Paper Bot!\n\n"
            "Here, you can easily purchase previous year question papers for different departments and semesters of MAKAUT college.\n\n"
            "Each paper costs 5 stars. You can also purchase papers in bulk for a discounted rate!\n\n"
            "You can buy stars in advance using /buy_star <amount> or pay stars directly when purchasing a paper.\n\n"
            "Use the quick buttons below to get started!"
        )
        keyboard = [
            [InlineKeyboardButton("Topup Wallet ⭐", callback_data="topup_wallet"), InlineKeyboardButton("Purchase Questions", callback_data="purchase_questions")],
            [InlineKeyboardButton("Profile", callback_data="profile"), InlineKeyboardButton("About Us", callback_data="about_us")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(welcome_message, reply_markup=reply_markup)
    
    # Clear user data related to current purchase flow
    context.user_data.clear()

async def back_to_dept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please choose a department:", reply_markup=get_department_keyboard())
    if 'department' in context.user_data: del context.user_data['department']
    if 'semester' in context.user_data: del context.user_data['semester']
    if 'year' in context.user_data: del context.user_data['year']

async def back_to_sem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    department = context.user_data.get('department')
    if department:
        await query.edit_message_text(f"You selected {department}. Now choose a semester:", reply_markup=get_semester_keyboard(department))
        if 'semester' in context.user_data: del context.user_data['semester']
        if 'year' in context.user_data: del context.user_data['year']
    else:
        await query.edit_message_text("Department not found in context. Returning to department selection.")
        await back_to_dept_callback(update, context)

async def back_to_year_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    department = context.user_data.get('department')
    semester = context.user_data.get('semester')

    if department and semester:
        db = SessionLocal()
        available_years = db.query(QuestionPaper.year).filter(
            QuestionPaper.department == department,
            QuestionPaper.semester == semester,
            QuestionPaper.year != ""
        ).distinct().all()
        db.close()

        if available_years:
            keyboard = chunk_buttons([year[0] for year in available_years], "year")
            keyboard.append([InlineKeyboardButton("Back", callback_data="back_to_sem"), InlineKeyboardButton("Main Menu", callback_data="main_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"You selected {semester}. Now choose a year for {department} department:", reply_markup=reply_markup)
            if 'year' in context.user_data: del context.user_data['year']
        else:
            await query.edit_message_text("No years found for this department and semester.", reply_markup=error_keyboard("back_to_sem"))
    else:
        await query.edit_message_text("Department or semester not found in context.", reply_markup=error_keyboard("back_to_dept"))


async def send_paper_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, paper: QuestionPaper):
    """Send paper PDF to user"""
    try:
        # Create temp directory if it doesn't exist
        os.makedirs("temp", exist_ok=True)
        
        # Download file from Firebase
        file_name = paper.paper_name
        temp_path = f"temp/{file_name}"
        
        # Get file name from URL
        firebase_path = paper.file_url.split('/')[-1]
        await download_file_from_firebase(f"papers/{firebase_path}", temp_path)
        
        # Send file to user
        with open(temp_path, 'rb') as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                filename=file_name,
                caption=f"📚 {paper.department} - Semester {paper.semester} - Year {paper.year}"
            )
        
        # Clean up temp file
        os.remove(temp_path)
        
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Error sending file: {str(e)}")

# --- Admin/Testing Commands ---
async def add_stars_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This command is for testing purposes. In a real bot, stars would be acquired via payment.
    try:
        stars_to_add = int(context.args[0])
        if stars_to_add <= 0:
            await update.message.reply_text("Please provide a positive number of stars to add.")
            return
        user_telegram_id = update.effective_user.id
        db = SessionLocal()
        user = db.query(User).filter(User.telegram_id == user_telegram_id).first()
        if user:
            user.stars += stars_to_add
            db.add(user)
            db.commit()
            db.refresh(user)
            await update.message.reply_text(f"Successfully added {stars_to_add} stars. Your new balance: {user.stars}")
        else:
            await update.message.reply_text("User not found. Please start the bot with /start first to register.")
        db.close()
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /add_stars <amount> (e.g., /add_stars 100)")
    except Exception as e:
        await update.message.reply_text(f"An error occurred while adding stars: {e}")

async def buy_star_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        try:
            amount = int(context.args[0])
            if amount <= 0:
                await update.message.reply_text("Please provide a positive number of stars to buy.")
                return
            await generate_star_invoice(update, context, amount)
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: /buy_star <amount> (e.g., /buy_star 100)")
    else:
        keyboard = [
            [InlineKeyboardButton("Cancel", callback_data="cancel_star_purchase")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.user_data['previous_screen'] = 'main_menu'  # Store the previous screen
        await update.message.reply_text(
            "Please enter the number of stars you want to purchase:",
            reply_markup=reply_markup
        )
        context.user_data['waiting_for_star_amount'] = True

async def generate_star_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    title = f"Buy {amount} Telegram Stars"
    description = f"Add {amount} stars to your profile balance."
    payload = f"buy_star_{amount}"
    prices = [LabeledPrice(label=f'{amount} Stars', amount=amount)]
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # Empty for Telegram Stars
        currency="XTR",
        prices=prices,
        is_flexible=False,
    )

async def handle_star_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_star_amount'):
        return

    try:
        amount = int(update.message.text)
        if amount <= 0:
            await update.message.reply_text("Please provide a positive number of stars to buy.")
            return
        context.user_data.pop('waiting_for_star_amount')
        await generate_star_invoice(update, context, amount)
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

async def topup_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Cancel", callback_data="cancel_star_purchase")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['previous_screen'] = 'main_menu'  # Store the previous screen
    await query.edit_message_text(
        "Please enter the number of stars you want to purchase:",
        reply_markup=reply_markup
    )
    context.user_data['waiting_for_star_amount'] = True

async def pre_checkout_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = update.message.successful_payment.invoice_payload
    db = SessionLocal()
    user_telegram_id = update.effective_user.id
    user = await get_or_create_user(user_telegram_id, db)

    if payload.startswith("buy_star_"):
        amount = int(payload.split("_")[2])
        user.stars += amount
        db.add(user)
        db.commit()
        db.refresh(user)
        await update.message.reply_text(f"🎉 Payment successful! {amount} stars have been added to your balance. Your new balance: {user.stars}")
    elif payload.startswith("single_paper_"):
        paper_id = int(payload.split("_")[2])
        paper = db.query(QuestionPaper).filter(QuestionPaper.id == paper_id).first()
        if paper and paper not in user.purchased_papers:
            user.purchased_papers.append(paper)
            db.add(user)
            db.commit()
            db.refresh(user)
            await update.message.reply_text(f"🎉 Payment successful! You've purchased {paper.paper_name}. Sending it now...")
            await send_paper_pdf(update, context, paper)
    elif payload.startswith("bulk_purchase_"):
        parts = payload.split("_")
        department = parts[2]
        semester = parts[3]
        year = parts[4]
        papers_in_year = db.query(QuestionPaper).filter(
            QuestionPaper.department == department,
            QuestionPaper.semester == semester,
            QuestionPaper.year == year
        ).all()
        purchased_count = 0
        for paper in papers_in_year:
            if paper not in user.purchased_papers:
                user.purchased_papers.append(paper)
                purchased_count += 1
        if purchased_count > 0:
            db.add(user)
            db.commit()
            db.refresh(user)
            await update.message.reply_text(f"🎉 Payment successful! You've purchased {purchased_count} papers for {department} - {semester} - {year}. Sending them now...")
            for paper in papers_in_year:
                await send_paper_pdf(update, context, paper)
        else:
            await update.message.reply_text("You already owned all papers in this bulk set. No new papers were sent.")
    db.close()

# --- Admin Access Decorator ---
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("❌ You are not authorized to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Department Commands ---
@admin_only
async def add_dept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /add_dept [department_name]")
        return
    db = SessionLocal()
    exists = db.query(QuestionPaper).filter(QuestionPaper.department == dept).first()
    if exists:
        await update.message.reply_text(f"Department '{dept}' already exists.")
    else:
        db.add(QuestionPaper(department=dept, semester="", year="", paper_name="__DEPT__", file_path="", price=0))
        db.commit()
        await update.message.reply_text(f"Department '{dept}' added.")
    db.close()

@admin_only
async def remove_dept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /remove_dept [department_name]")
        return
    db = SessionLocal()
    deleted = db.query(QuestionPaper).filter(QuestionPaper.department == dept).delete()
    db.commit()
    await update.message.reply_text(f"Department '{dept}' and all linked data removed ({deleted} records).")
    db.close()

@admin_only
async def list_dept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    depts = db.query(QuestionPaper.department).distinct().all()
    db.close()
    depts = [d[0] for d in depts if d[0] and d[0] != ""]
    if depts:
        await update.message.reply_text("Departments:\n" + "\n".join(depts))
    else:
        await update.message.reply_text("No departments found.")

# --- Semester Commands ---
@admin_only
async def add_sem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem = context.args[0], context.args[1]
    except IndexError:
        await update.message.reply_text("Usage: /add_sem [department_name] [semester_number]")
        return
    db = SessionLocal()
    exists = db.query(QuestionPaper).filter(QuestionPaper.department == dept, QuestionPaper.semester == sem).first()
    if exists:
        await update.message.reply_text(f"Semester '{sem}' already exists for department '{dept}'.")
    else:
        db.add(QuestionPaper(department=dept, semester=sem, year="", paper_name="__SEM__", file_path="", price=0))
        db.commit()
        await update.message.reply_text(f"Semester '{sem}' added to department '{dept}'.")
    db.close()

@admin_only
async def remove_sem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem = context.args[0], context.args[1]
    except IndexError:
        await update.message.reply_text("Usage: /remove_sem [department_name] [semester_name]")
        return
    db = SessionLocal()
    deleted = db.query(QuestionPaper).filter(QuestionPaper.department == dept, QuestionPaper.semester == sem).delete()
    db.commit()
    await update.message.reply_text(f"Semester '{sem}' and all linked data removed from department '{dept}' ({deleted} records).")
    db.close()

@admin_only
async def list_sem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /list_sem [department_name]")
        return
    db = SessionLocal()
    sems = db.query(QuestionPaper.semester).filter(QuestionPaper.department == dept).distinct().all()
    db.close()
    sems = [s[0] for s in sems if s[0] and s[0] != ""]
    if sems:
        await update.message.reply_text(f"Semesters in {dept}:\n" + "\n".join(sems))
    else:
        await update.message.reply_text(f"No semesters found for department '{dept}'.")

# --- Year Commands ---
@admin_only
async def add_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem, year = context.args[0], context.args[1], context.args[2]
    except IndexError:
        await update.message.reply_text("Usage: /add_year [department_name] [semester_number] [exam_year]")
        return
    db = SessionLocal()
    exists = db.query(QuestionPaper).filter(QuestionPaper.department == dept, QuestionPaper.semester == sem, QuestionPaper.year == year).first()
    if exists:
        await update.message.reply_text(f"Year '{year}' already exists for {dept} semester {sem}.")
    else:
        db.add(QuestionPaper(department=dept, semester=sem, year=year, paper_name="__YEAR__", file_path="", price=0))
        db.commit()
        await update.message.reply_text(f"Year '{year}' added to {dept} semester {sem}.")
    db.close()

@admin_only
async def remove_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem, year = context.args[0], context.args[1], context.args[2]
    except IndexError:
        await update.message.reply_text("Usage: /remove_year [department_name] [semester_number] [exam_year]")
        return
    db = SessionLocal()
    deleted = db.query(QuestionPaper).filter(QuestionPaper.department == dept, QuestionPaper.semester == sem, QuestionPaper.year == year).delete()
    db.commit()
    await update.message.reply_text(f"Year '{year}' and all linked question papers removed from {dept} semester {sem} ({deleted} records).")
    db.close()

@admin_only
async def list_years(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem = context.args[0], context.args[1]
    except IndexError:
        await update.message.reply_text("Usage: /list_years [department_name] [semester_number]")
        return
    db = SessionLocal()
    years = db.query(QuestionPaper.year).filter(QuestionPaper.department == dept, QuestionPaper.semester == sem).distinct().all()
    db.close()
    years = [y[0] for y in years if y[0] and y[0] != ""]
    if years:
        await update.message.reply_text(f"Years in {dept} semester {sem}:\n" + "\n".join(years))
    else:
        await update.message.reply_text(f"No years found for {dept} semester {sem}.")

# --- Question Paper Commands ---
@admin_only
async def upload_qp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem, year, subject = context.args[0], context.args[1], context.args[2], " ".join(context.args[3:])
    except IndexError:
        await update.message.reply_text("Usage: /upload_qp [department_name] [semester_number] [exam_year] [subject_name]")
        return
    context.user_data['upload_qp'] = {
        'department': dept,
        'semester': sem,
        'year': year,
        'subject': subject
    }
    await update.message.reply_text(f"Please send the question paper file (PDF, PNG, JPEG) for {dept} {sem} {year} {subject}.")

@admin_only
async def remove_qp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem, year, subject = context.args[0], context.args[1], context.args[2], " ".join(context.args[3:])
    except IndexError:
        await update.message.reply_text("Usage: /remove_qp [department_name] [semester_number] [exam_year] [subject_name]")
        return
    db = SessionLocal()
    deleted = db.query(QuestionPaper).filter(
        QuestionPaper.department == dept,
        QuestionPaper.semester == sem,
        QuestionPaper.year == year,
        QuestionPaper.paper_name == subject
    ).delete()
    db.commit()
    await update.message.reply_text(f"Question paper '{subject}' removed from {dept} {sem} {year} ({deleted} records).")
    db.close()

@admin_only
async def list_qp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dept, sem, year = context.args[0], context.args[1], context.args[2]
    except IndexError:
        await update.message.reply_text("Usage: /list_qp [department_name] [semester_number] [exam_year]")
        return
    db = SessionLocal()
    qps = db.query(QuestionPaper.paper_name).filter(
        QuestionPaper.department == dept,
        QuestionPaper.semester == sem,
        QuestionPaper.year == year,
        QuestionPaper.paper_name != "__DEPT__",
        QuestionPaper.paper_name != "__SEM__",
        QuestionPaper.paper_name != "__YEAR__"
    ).all()
    db.close()
    qps = [q[0] for q in qps if q[0] and q[0] != ""]
    if qps:
        await update.message.reply_text(f"Question Papers in {dept} {sem} {year}:\n" + "\n".join(qps))
    else:
        await update.message.reply_text(f"No question papers found for {dept} {sem} {year}.")

# --- File Upload Handler for Admins ---
@admin_only
async def admin_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads from admin"""
    try:
        # Check if this is a response to upload_qp command
        if 'upload_qp' not in context.user_data:
            await update.message.reply_text("❌ Please use /upload_qp command first to specify paper details.")
            return

        paper_info = context.user_data['upload_qp']
        
        # Get file info
        if update.message.document:
            file = update.message.document
            file_name = file.file_name
        elif update.message.photo:
            file = update.message.photo[-1]  # Get the largest photo
            file_name = f"{paper_info['subject']}_{paper_info['year']}.jpg"
        else:
            await update.message.reply_text("❌ Please send a document or photo.")
            return

        # Create temp directory if it doesn't exist
        os.makedirs("temp", exist_ok=True)
        
        try:
            # Download file to temp directory
            file_path = f"temp/{file_name}"
            telegram_file = await context.bot.get_file(file.file_id)
            await telegram_file.download_to_drive(file_path)
            
            # Upload to Firebase Storage
            firebase_path = f"papers/{paper_info['department']}/{paper_info['semester']}/{paper_info['year']}/{file_name}"
            file_url = await upload_file_to_firebase(file_path, firebase_path)
            
            # Save to database
            db = SessionLocal()
            try:
                new_paper = QuestionPaper(
                    department=paper_info['department'],
                    semester=paper_info['semester'],
                    year=paper_info['year'],
                    paper_name=paper_info['subject'],
                    file_url=file_url,
                    price=5  # Default price
                )
                db.add(new_paper)
                db.commit()
                
                await update.message.reply_text(
                    "✅ File uploaded successfully!\n"
                    f"Department: {paper_info['department']}\n"
                    f"Semester: {paper_info['semester']}\n"
                    f"Year: {paper_info['year']}\n"
                    f"Subject: {paper_info['subject']}\n"
                    f"Price: 5 stars"
                )
                
                # Notify users about new paper
                await notify_new_paper(
                    paper_info['department'],
                    paper_info['semester'],
                    paper_info['year'],
                    paper_info['subject'],
                    context
                )
                
            except Exception as e:
                db.rollback()
                raise e
            finally:
                db.close()
                
        except Exception as e:
            await update.message.reply_text(f"❌ Error processing file: {str(e)}")
        finally:
            # Clean up temp file
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Error cleaning up temp file: {str(e)}")
            
            # Clear the upload context
            if 'upload_qp' in context.user_data:
                del context.user_data['upload_qp']
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error uploading file: {str(e)}")
        # Clear the upload context on error
        if 'upload_qp' in context.user_data:
            del context.user_data['upload_qp']

# --- Admin-Only Commands ---
@admin_only
async def adminbuystar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stars_to_add = int(context.args[0])
        if stars_to_add <= 0:
            await update.message.reply_text("Please provide a positive number of stars to add.")
            return
        user_telegram_id = update.effective_user.id
        db = SessionLocal()
        user = db.query(User).filter(User.telegram_id == user_telegram_id).first()
        if user:
            user.stars += stars_to_add
            db.add(user)
            db.commit()
            db.refresh(user)
            await update.message.reply_text(f"Successfully added {stars_to_add} stars. Your new balance: {user.stars}")
        else:
            await update.message.reply_text("User not found. Please start the bot with /start first to register.")
        db.close()
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /adminbuystar <amount> (e.g., /adminbuystar 100)")
    except Exception as e:
        await update.message.reply_text(f"An error occurred while adding stars: {e}")

@admin_only
async def admin_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
    "🛠️ <b>Admin Commands - Quick Guide:</b>\n\n"

    "<b>📚 Department Management</b>\n"
    "<code>/add_dept [department_name]</code> — ➕ Add a new department\n"
    "<code>/remove_dept [department_name]</code> — ❌ Remove an existing department\n"
    "<code>/list_dept</code> — 📄 View all departments\n\n"

    "<b>🎓 Semester Management</b>\n"
    "<code>/add_sem [department_name] [semester_name]</code> — ➕ Add a semester to a department\n"
    "<code>/remove_sem [department_name] [semester_name]</code> — ❌ Remove a semester from a department\n"
    "<code>/list_sem [department_name]</code> — 📄 View semesters under a department\n\n"

    "<b>📅 Year Management</b>\n"
    "<code>/add_year [department_name] [semester_name] [year]</code> — ➕ Add a year to a semester\n"
    "<code>/remove_year [department_name] [semester_name] [year]</code> — ❌ Remove a year from a semester\n"
    "<code>/list_years [department_name] [semester_name]</code> — 📄 View years under a semester\n\n"

    "<b>📄 Question Paper Management</b>\n"
    "<code>/upload_qp [department_name] [semester_name] [year] [subject]</code> — ⬆️ Upload a question paper\n"
    "<code>/remove_qp [department_name] [semester_name] [year] [subject]</code> — ❌ Remove a question paper\n"
    "<code>/list_qp [department_name] [semester_name] [year]</code> — 📄 View all question papers for a year\n\n"

    "<b>⭐ Testing & Stars</b>\n"
    "<code>/adminbuystar [amount]</code> — 💰 Add stars to your account (For testing only)\n\n"

    "<b>❔ Help</b>\n"
    "<code>/admin_help</code> — 📖 View this admin command guide anytime\n\n"

    "✅ <i>Tip:</i> Use <b>[ ]</b> for required input — replace them with actual names/values.\n"
    "<i>Example:</i> <code>/add_dept Computer_Science</code>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

@admin_only
async def notify_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        help_text = (
            "📢 <b>Notification Command Usage:</b>\n\n"
            "1. Send to all users:\n"
            "<code>/notify_all all</code>\n\n"
            "2. Send to specific users:\n"
            "<code>/notify_all 123456789 987654321</code>\n\n"
            "After using the command, send your message (text, photo, video, document) with optional caption."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
        return

    # Store the target users in context
    if context.args[0].lower() == 'all':
        db = SessionLocal()
        context.user_data['notify_targets'] = [user.telegram_id for user in db.query(User).all()]
        db.close()
        await update.message.reply_text("Please send your message (text, photo, video, document) with optional caption. It will be sent to all users.")
    else:
        try:
            user_ids = [int(uid) for uid in context.args]
            context.user_data['notify_targets'] = user_ids
            await update.message.reply_text(f"Please send your message (text, photo, video, document) with optional caption. It will be sent to {len(user_ids)} users.")
        except ValueError:
            await update.message.reply_text("Invalid user IDs. Please provide valid numeric user IDs.")

async def handle_notification_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'notify_targets' not in context.user_data:
        return

    targets = context.user_data['notify_targets']
    success_count = 0
    failed_count = 0

    # Handle different types of messages
    if update.message.text:
        # Text message
        for user_id in targets:
            try:
                await context.bot.send_message(chat_id=user_id, text=update.message.text)
                success_count += 1
            except Exception:
                failed_count += 1

    elif update.message.photo:
        # Photo with optional caption
        photo = update.message.photo[-1]  # Get the highest resolution
        caption = update.message.caption or ""
        for user_id in targets:
            try:
                await context.bot.send_photo(chat_id=user_id, photo=photo.file_id, caption=caption)
                success_count += 1
            except Exception:
                failed_count += 1

    elif update.message.video:
        # Video with optional caption
        video = update.message.video
        caption = update.message.caption or ""
        for user_id in targets:
            try:
                await context.bot.send_video(chat_id=user_id, video=video.file_id, caption=caption)
                success_count += 1
            except Exception:
                failed_count += 1

    elif update.message.document:
        # Document with optional caption
        document = update.message.document
        caption = update.message.caption or ""
        for user_id in targets:
            try:
                await context.bot.send_document(chat_id=user_id, document=document.file_id, caption=caption)
                success_count += 1
            except Exception:
                failed_count += 1

    # Clear the notification targets
    context.user_data.pop('notify_targets', None)

    # Send summary to admin
    await update.message.reply_text(
        f"📊 Notification Summary:\n"
        f"✅ Successfully sent: {success_count}\n"
        f"❌ Failed to send: {failed_count}"
    )

async def notify_new_paper(dept, sem, year, subject, context):
    db = SessionLocal()
    user_ids = [user.telegram_id for user in db.query(User).all()]
    db.close()
    notif = f"🆕 New question paper uploaded!\n<b>{dept} {sem} {year} - {subject}</b> is now available.\nUse /purchase to get it!"
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=notif, parse_mode=ParseMode.HTML)
        except Exception:
            continue

async def purchase_questions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await purchase_command(query, context)

async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_profile(update, context, is_command=False)

async def about_us_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_about_us(update, context, is_command=False)

@admin_only
async def add_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        help_text = (
            "📦 <b>Bulk Addition Command Usage:</b>\n\n"
            "1️⃣ Add multiple departments:\n"
            "<code>/add_bulk dept CSE,IT,EE,ME,CIVIL</code>\n\n"
            "2️⃣ Add multiple semesters for a department:\n"
            "<code>/add_bulk sem CSE:Sem1,Sem2,Sem3,Sem4</code>\n\n"
            "3️⃣ Add multiple years for a department's semester:\n"
            "<code>/add_bulk year CSE:Sem1:2021,2022,2023</code>"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
        return

    operation = context.args[0].lower()
    data = context.args[1]
    db = SessionLocal()
    success_count = 0
    error_count = 0
    response_messages = []

    try:
        if operation == "dept":
            departments = [d.strip() for d in data.split(",")]
            for dept in departments:
                if not dept:
                    continue
                exists = db.query(QuestionPaper).filter(QuestionPaper.department == dept).first()
                if not exists:
                    db.add(QuestionPaper(department=dept, semester="", year="", paper_name="__DEPT__", file_path="", price=0))
                    success_count += 1
                else:
                    error_count += 1
                    response_messages.append(f"Department '{dept}' already exists")
            db.commit()
            await update.message.reply_text(f"✅ Successfully added {success_count} departments.\n❌ {error_count} departments already existed.")

        elif operation == "sem":
            try:
                dept, sems = data.split(":")
                sems = [s.strip() for s in sems.split(",")]
                for sem in sems:
                    if not sem:
                        continue
                    exists = db.query(QuestionPaper).filter(
                        QuestionPaper.department == dept,
                        QuestionPaper.semester == sem
                    ).first()
                    if not exists:
                        db.add(QuestionPaper(department=dept, semester=sem, year="", paper_name="__SEM__", file_path="", price=0))
                        success_count += 1
                    else:
                        error_count += 1
                        response_messages.append(f"Semester '{sem}' already exists for department '{dept}'")
                db.commit()
                await update.message.reply_text(f"✅ Successfully added {success_count} semesters to department '{dept}'.\n❌ {error_count} semesters already existed.")
            except ValueError:
                await update.message.reply_text("❌ Invalid format. Use: /add_bulk sem Department:Sem1,Sem2,Sem3")

        elif operation == "year":
            try:
                dept, sem, years = data.split(":")
                years = [y.strip() for y in years.split(",")]
                for year in years:
                    if not year:
                        continue
                    exists = db.query(QuestionPaper).filter(
                        QuestionPaper.department == dept,
                        QuestionPaper.semester == sem,
                        QuestionPaper.year == year
                    ).first()
                    if not exists:
                        db.add(QuestionPaper(department=dept, semester=sem, year=year, paper_name="__YEAR__", file_path="", price=0))
                        success_count += 1
                    else:
                        error_count += 1
                        response_messages.append(f"Year '{year}' already exists for {dept} semester {sem}")
                db.commit()
                await update.message.reply_text(f"✅ Successfully added {success_count} years to {dept} semester {sem}.\n❌ {error_count} years already existed.")
            except ValueError:
                await update.message.reply_text("❌ Invalid format. Use: /add_bulk year Department:Semester:2021,2022,2023")

        else:
            await update.message.reply_text("❌ Invalid operation. Use 'dept', 'sem', or 'year'")

    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"❌ An error occurred: {str(e)}")
    finally:
        db.close()

    if response_messages:
        await update.message.reply_text("📝 Details:\n" + "\n".join(response_messages))

async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    welcome_message = (
        "Hello! 👋 Welcome to the MAKAUT Question Paper Bot!\n\n"
        "Here, you can easily purchase previous year question papers for different departments and semesters of MAKAUT college.\n\n"
        "Each paper costs 5 stars. You can also purchase papers in bulk for a discounted rate!\n\n"
        "You can buy stars in advance using /buy_star <amount> or pay stars directly when purchasing a paper.\n\n"
        "Use the quick buttons below to get started!"
    )
    keyboard = [
        [InlineKeyboardButton("Topup Wallet ⭐", callback_data="topup_wallet"), InlineKeyboardButton("Purchase Questions", callback_data="purchase_questions")],
        [InlineKeyboardButton("Profile", callback_data="profile"), InlineKeyboardButton("About Us", callback_data="about_us")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(welcome_message, reply_markup=reply_markup)

# --- Admin Channel Management Commands ---
@admin_only
async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide the channel username.\n"
            "Example: /add_channel @channel_username"
        )
        return
    
    channel = context.args[0]
    if not channel.startswith('@'):
        channel = '@' + channel
    
    if channel in REQUIRED_CHANNELS:
        await update.message.reply_text("⚠️ This channel is already in the list!")
        return
    
    try:
        # Try to get channel info to verify it exists and bot has access
        chat = await context.bot.get_chat(channel)
        bot_member = await chat.get_member(context.bot.id)
        if bot_member.status != ChatMember.ADMINISTRATOR:
            await update.message.reply_text(
                "⚠️ Please make the bot an admin in the channel first!"
            )
            return
        
        REQUIRED_CHANNELS.append(channel)
        await update.message.reply_text(f"✅ Channel {channel} added successfully!")
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error adding channel: {str(e)}\n"
            "Make sure:\n"
            "1. The channel exists\n"
            "2. The bot is an admin in the channel"
        )

@admin_only
async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide the channel username.\n"
            "Example: /remove_channel @channel_username"
        )
        return
    
    channel = context.args[0]
    if not channel.startswith('@'):
        channel = '@' + channel
    
    if channel in REQUIRED_CHANNELS:
        REQUIRED_CHANNELS.remove(channel)
        await update.message.reply_text(f"✅ Channel {channel} removed successfully!")
    else:
        await update.message.reply_text("⚠️ This channel is not in the list!")

@admin_only
async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not REQUIRED_CHANNELS:
        await update.message.reply_text("No required channels set.")
        return
    
    channels_text = "\n".join([f"• {channel}" for channel in REQUIRED_CHANNELS])
    await update.message.reply_text(
        "<b>Required Channels:</b>\n\n"
        f"{channels_text}",
        parse_mode=ParseMode.HTML
    )

# --- Callback Handlers ---
async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    is_subscribed = await check_channel_subscription(update, context)
    if is_subscribed:
        await start_command(update, context)

def is_bot_running():
    pid_file = Path("bot.pid")
    if pid_file.exists():
        try:
            with open(pid_file) as f:
                old_pid = int(f.read().strip())
            # Check if process with this PID exists
            os.kill(old_pid, 0)
            return True
        except (OSError, ValueError):
            # Process not running or PID file is invalid
            pid_file.unlink(missing_ok=True)
    return False

def save_pid():
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))

def cleanup():
    try:
        # Remove PID file
        Path("bot.pid").unlink(missing_ok=True)
        # Clean temp directory
        if os.path.exists("temp"):
            for file in os.listdir("temp"):
                os.remove(os.path.join("temp", file))
            os.rmdir("temp")
    except Exception as e:
        print(f"Error during cleanup: {e}")

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Register error handler
    application.add_error_handler(error_handler)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("about_us", about_us_command))
    application.add_handler(CommandHandler("purchase", purchase_command))
    application.add_handler(CommandHandler("add_stars", add_stars_command))
    application.add_handler(CommandHandler("buy_star", buy_star_command))
    application.add_handler(CommandHandler("adminbuystar", adminbuystar_command))
    application.add_handler(CommandHandler("admin_help", admin_help_command))
    application.add_handler(CommandHandler("notify_all", notify_all_command))

    # File Handler for Admins
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, admin_file_handler))

    # Message Handler for Star Amount
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_star_amount))

    # Callback Query Handlers for purchase flow
    application.add_handler(CallbackQueryHandler(department_callback, pattern=r'^dept_'))
    application.add_handler(CallbackQueryHandler(semester_callback, pattern=r'^sem_'))
    application.add_handler(CallbackQueryHandler(year_callback, pattern=r'^year_'))
    application.add_handler(CallbackQueryHandler(select_paper_callback, pattern=r'^select_paper_'))
    application.add_handler(CallbackQueryHandler(bulk_purchase_callback, pattern=r'^bulk_purchase$'))
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern=r'^main_menu$'))
    application.add_handler(CallbackQueryHandler(back_to_dept_callback, pattern=r'^back_to_dept$'))
    application.add_handler(CallbackQueryHandler(back_to_sem_callback, pattern=r'^back_to_sem$'))
    application.add_handler(CallbackQueryHandler(back_to_year_callback, pattern=r'^back_to_year$'))
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_query))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # Department
    application.add_handler(CommandHandler("add_dept", add_dept))
    application.add_handler(CommandHandler("remove_dept", remove_dept))
    application.add_handler(CommandHandler("list_dept", list_dept))
    # Semester
    application.add_handler(CommandHandler("add_sem", add_sem))
    application.add_handler(CommandHandler("remove_sem", remove_sem))
    application.add_handler(CommandHandler("list_sem", list_sem))
    # Year
    application.add_handler(CommandHandler("add_year", add_year))
    application.add_handler(CommandHandler("remove_year", remove_year))
    application.add_handler(CommandHandler("list_years", list_years))
    # Question Paper
    application.add_handler(CommandHandler("upload_qp", upload_qp))
    application.add_handler(CommandHandler("remove_qp", remove_qp))
    application.add_handler(CommandHandler("list_qp", list_qp))
    # Bulk Operations
    application.add_handler(CommandHandler("add_bulk", add_bulk))
    # Channel Management
    application.add_handler(CommandHandler("add_channel", add_channel_command))
    application.add_handler(CommandHandler("remove_channel", remove_channel_command))
    application.add_handler(CommandHandler("list_channels", list_channels_command))
    # Subscription Check
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))

    # Start the Bot with a clean shutdown
    print("Bot starting...")
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"Error running bot: {e}")
    finally:
        print("Bot shutting down...")
        cleanup()

if __name__ == '__main__':
    try:
        if is_bot_running():
            print("Error: Bot is already running!")
            sys.exit(1)
            
        # Save PID and register cleanup
        save_pid()
        atexit.register(cleanup)
        
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Initialize database
        init_db()
        
        # Start the bot
        print("Bot starting...")
        main()
    except Exception as e:
        print(f"Fatal error: {e}")
        cleanup()
        sys.exit(1) 