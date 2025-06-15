# MAKAUT Question Papers Bot & Mini App

A Telegram bot and Mini App for purchasing and managing MAKAUT question papers.

## Features

### Bot Features
- Purchase question papers using Telegram Stars
- Bulk purchase with 10% discount
- Admin commands for managing departments, semesters, years, and papers
- User profile and purchase history
- Star balance management

### Mini App Features
- Beautiful, responsive web interface
- Four main sections:
  1. Question Papers - Browse and purchase papers
  2. Topup Wallet - Add stars to your balance
  3. Purchase History - View and access purchased papers
  4. Profile - View statistics and achievements
- Real-time synchronization with bot data
- Secure authentication using Telegram WebApp
- 3D-like UI elements and smooth animations

## Setup

### Prerequisites
- Python 3.8 or higher
- PostgreSQL database
- Telegram Bot Token
- Domain for hosting the Mini App

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/makaut-question-papers.git
cd makaut-question-papers
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file with your configuration:
```env
TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
ADMIN_IDS=123456789,987654321
```

5. Initialize the database:
```bash
python -c "from database import init_db; init_db()"
```

### Running the Bot

1. Start the bot:
```bash
python bot.py
```

2. Start the API server:
```bash
python api.py
```

### Setting up the Mini App

1. Create a new Mini App in BotFather:
   - Use `/newapp` command
   - Set the web app URL to your domain
   - Configure the app settings

2. Deploy the frontend files:
   - Upload `index.html`, `styles.css`, and `app.js` to your web server
   - Ensure CORS is properly configured
   - Set up SSL for secure connections

3. Update the bot's web app URL:
   - Use `/setwebapp` command in BotFather
   - Set the URL to your deployed Mini App

## Development

### Project Structure
```
makaut-question-papers/
├── bot.py              # Telegram bot implementation
├── api.py             # Flask API for Mini App
├── database.py        # Database models and utilities
├── config.py          # Configuration settings
├── requirements.txt   # Python dependencies
├── static/           # Frontend files
│   ├── index.html    # Main HTML file
│   ├── styles.css    # CSS styles
│   └── app.js        # Frontend JavaScript
└── README.md         # This file
```

### Adding New Features

1. Bot Features:
   - Add new command handlers in `bot.py`
   - Update database models in `database.py` if needed

2. Mini App Features:
   - Add new UI components in `index.html`
   - Style new components in `styles.css`
   - Add functionality in `app.js`
   - Create corresponding API endpoints in `api.py`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 