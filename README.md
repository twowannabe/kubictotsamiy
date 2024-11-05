# Telegram Moderation Bot

This repository contains a Telegram bot designed to moderate a Telegram group or channel. The bot provides functionalities such as muting, banning, and wiping messages of users, as well as managing a list of authorized users who can control the bot. The bot is implemented using Python and PostgreSQL for database management.

## Features

- **Mute Users**: Temporarily mute a user for a specified duration.
- **Unmute Users**: Unmute a user, allowing them to send messages again.
- **Ban Users**: Temporarily ban a user from the group for a specified duration.
- **Unban Users**: Unban a user, restoring their ability to interact with the group.
- **Wipe Messages**: Authorized users can wipe their own messages from the group.
- **Edit Handling**: The bot can handle edited messages and log relevant information.
- **Logging**: Activity logs are stored for monitoring bot actions without exposing user privacy.

## Getting Started

These instructions will help you get a copy of the project up and running on your local machine.

### Prerequisites

- Python 3.8+
- PostgreSQL
- Telegram Bot Token (can be obtained from [BotFather](https://t.me/botfather))
- Environment variables managed via `.env` file

### Installation

1. **Clone the Repository**

   ```sh
   git clone https://github.com/twowannabe/kubictotsamiy.git
   cd kubictotsamiy
   ```

2. **Create a Virtual Environment and Install Dependencies**

   ```sh
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Create a ********`.env`******** File**

   Create a `.env` file in the root directory of the project and provide the following variables:

   ```env
   TELEGRAM_API_TOKEN=your_telegram_bot_token_here
   DB_NAME=your_database_name
   DB_USER=your_database_user
   DB_PASSWORD=your_database_password
   DB_HOST=your_database_host
   DB_PORT=your_database_port
   AUTHORIZED_USERS=123456789,987654321,112233445  # Comma-separated list of authorized user IDs
   ```

4. **Set Up PostgreSQL Database**

   Make sure you have a PostgreSQL database set up with the necessary permissions. The bot will create the required tables if they do not exist.

5. **Run the Bot**

   Start the bot using the following command:

   ```sh
   python bot.py
   ```

## Usage

Once the bot is up and running, authorized users can use the following commands in the Telegram group:

- `/mute [duration]`: Mute a user for the specified duration (in minutes). Default is 10 minutes. This command must be used in reply to the user's message.
- `/unmute`: Unmute a user. This command must be used in reply to the user's message.
- `/ban [duration]`: Ban a user for the specified duration (in minutes). Default is 10 minutes. This command must be used in reply to the user's message.
- `/unban`: Unban a user. This command must be used in reply to the user's message.
- `/wipe`: Wipe all messages from the user who issues the command.
- `/help`: Display a help message explaining available commands.

## Contributing

Contributions are welcome! You can help improve this project by opening issues for bugs or feature requests, or by submitting pull requests. When contributing, please ensure that your changes maintain consistency with the existing code style and follow best practices.

### Feedback

Feedback, issue reports, and suggestions for new features or fixes are warmly welcomed. Please feel free to open issues and contribute ideas to enhance the functionality of the bot.

## Privacy Notice

This bot **does not store any messages** except for `message_id`, which is used to identify and delete messages in the group when necessary. We prioritize user privacy and encourage all contributors to adhere to these privacy standards.

## License

This project is licensed under terms specified in the [LICENSE](./LICENSE) file. You may use, copy, and modify the code for personal use only. Distribution and commercial use are not allowed without explicit permission from the author.

## Contact

Author: Volodymyr Kozlov

For any inquiries, feel free to reach out via GitHub or open an issue in this repository.

## Acknowledgments

- [Python Telegram Bot Library](https://github.com/python-telegram-bot/python-telegram-bot) for providing a great interface to interact with Telegram's Bot API.
- [PostgreSQL](https://www.postgresql.org/) for a reliable database solution.
