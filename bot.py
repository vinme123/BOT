import os
import logging
import random
import urllib.request
import json
import sqlite3
import datetime
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

ADMIN_IDS = [8772319266]  # Admin Telegram ID

LTC_WALLET = "ltc1q4sfca5qq6dvge6ax2xlkru8fvjzprhwrvnjhjk"

os.makedirs("stock_photos", exist_ok=True)

# ==================== დამხმარე ფუნქცია მხოლოდ უბნებისთვის (2 გვერდიგვერდ) ====================
def chunk_buttons(buttons_list, row_size=2):
    """ანაწილებს ღილაკების სიას მითითებულ ზომებად (იყენებენ მხოლოდ უბნები)"""
    return [buttons_list[i:i + row_size] for i in range(0, len(buttons_list), row_size)]

# ==================== SQLite Database ====================
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # მომხმარებლები
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            earned REAL DEFAULT 0.0,
            referrals_count INTEGER DEFAULT 0,
            referrer_id INTEGER,
            verified INTEGER DEFAULT 0
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    except sqlite3.OperationalError:
        pass

    # შეკვეთების ისტორია
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_name TEXT,
            district TEXT,
            price REAL,
            date TEXT,
            photo_path TEXT
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE purchases ADD COLUMN photo_path TEXT")
    except sqlite3.OperationalError:
        pass

    # მარაგები (Stock)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT,
            district_key TEXT,
            photo_path TEXT
        )
    """)
    # პროდუქტები (კატეგორიები)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_key TEXT PRIMARY KEY,
            name TEXT,
            price REAL
        )
    """)
    # უბნები
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS districts (
            district_key TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    # პროდუქტისა და უბნის კავშირი
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_districts (
            product_key TEXT,
            district_key TEXT,
            PRIMARY KEY (product_key, district_key)
        )
    """)

    # საწყისი მონაცემები
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        defaults_prod = [
            ("prod_meow_05", "Meow 0.5", 155.0),
            ("prod_meow_1", "Meow 1", 280.0),
            ("prod_meow_2", "Meow 2", 520.0),
            ("prod_meow_5", "Meow 5", 1450.0)
        ]
        cursor.executemany("INSERT OR IGNORE INTO products VALUES (?, ?, ?)", defaults_prod)

    cursor.execute("SELECT COUNT(*) FROM districts")
    if cursor.fetchone()[0] == 0:
        defaults_dist = [
            ("dist_saburtalo", "Saburtalo"),
            ("dist_samgori", "Samgori"),
            ("dist_digmi", "Digmis masivi"),
            ("dist_varketili", "Varketili")
        ]
        cursor.executemany("INSERT OR IGNORE INTO districts VALUES (?, ?)", defaults_dist)

    cursor.execute("SELECT COUNT(*) FROM product_districts")
    if cursor.fetchone()[0] == 0:
        defaults_links = [
            ("prod_meow_05", "dist_saburtalo"), ("prod_meow_05", "dist_samgori"),
            ("prod_meow_05", "dist_digmi"), ("prod_meow_05", "dist_varketili"),
            ("prod_meow_1", "dist_saburtalo"), ("prod_meow_1", "dist_samgori"),
            ("prod_meow_1", "dist_digmi"), ("prod_meow_1", "dist_varketili"),
            ("prod_meow_2", "dist_saburtalo"), ("prod_meow_2", "dist_samgori"),
            ("prod_meow_2", "dist_digmi"), ("prod_meow_2", "dist_varketili"),
            ("prod_meow_5", "dist_saburtalo"), ("prod_meow_5", "dist_samgori"),
            ("prod_meow_5", "dist_digmi"), ("prod_meow_5", "dist_varketili")
        ]
        cursor.executemany("INSERT OR IGNORE INTO product_districts VALUES (?, ?)", defaults_links)

    conn.commit()
    conn.close()

init_db()

def get_all_products():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT product_key, name, price FROM products")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}, {row[0]: row[2] for row in rows}

def get_all_districts():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT district_key, name FROM districts")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def get_product_districts(product_key):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT D.district_key, D.name 
        FROM product_districts PD
        JOIN districts D ON PD.district_key = D.district_key
        WHERE PD.product_key = ?
    """, (product_key,))
    rows = cursor.fetchall()
    conn.close()
    
    buttons = [InlineKeyboardButton(d_name, callback_data=f"dist_{d_key}") for d_key, d_name in rows]
    return chunk_buttons(buttons, 2)

def get_user(user_id, username=None):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, earned, referrals_count, referrer_id, verified, username FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, username, balance, earned, referrals_count, verified) VALUES (?, ?, 0.0, 0.0, 0, 0)", (user_id, username))
        conn.commit()
        row = (0.0, 0.0, 0, None, 0, username)
    else:
        if username and row[5] != username:
            cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            conn.commit()
    conn.close()
    
    balance = float(row[0]) if row[0] is not None else 0.0
    earned = float(row[1]) if row[1] is not None else 0.0
    referrals_count = int(row[2]) if row[2] is not None else 0
    referrer_id = row[3]
    verified = int(row[4]) if row[4] is not None else 0
    return (balance, earned, referrals_count, referrer_id, verified)

def update_user_db(user_id, balance=None, earned=None, referrals_count=None, referrer_id=None, verified=None):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    get_user(user_id)
    
    if balance is not None:
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (round(float(balance), 2), user_id))
    if earned is not None:
        cursor.execute("UPDATE users SET earned = ? WHERE user_id = ?", (round(float(earned), 2), user_id))
    if referrals_count is not None:
        cursor.execute("UPDATE users SET referrals_count = ? WHERE user_id = ?", (int(referrals_count), user_id))
    if referrer_id is not None:
        cursor.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (int(referrer_id), user_id))
    if verified is not None:
        cursor.execute("UPDATE users SET verified = ? WHERE user_id = ?", (int(verified), user_id))
        
    conn.commit()
    conn.close()

def get_user_purchases_count(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM purchases WHERE user_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_ltc_amount(gel_price):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gel"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode())
            ltc_in_gel = data['litecoin']['gel']
            return round(gel_price / ltc_in_gel, 6)
    except Exception:
        return round(gel_price / 180.0, 6)

def main_menu(user_id):
    bal, _, _, _, _ = get_user(user_id)
    purchases_count = get_user_purchases_count(user_id)
    
    keyboard = [
        [
            InlineKeyboardButton("Select City (1)", callback_data="select_city"),
            InlineKeyboardButton(f"Balance ({bal} ₾)", callback_data="balance")
        ],
        [
            InlineKeyboardButton(f"History ({purchases_count})", callback_data="history"),
            InlineKeyboardButton("Referral", callback_data="referral")
        ],
        [
            InlineKeyboardButton("Owner ↗", url="https://t.me"),
            InlineKeyboardButton("Group ↗", url="https://t.me")
        ]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username
    balance, earned, ref_count, referrer_id, verified = get_user(user_id, username)

    if context.args and len(context.args) > 0:
        try:
            ref_from_link = int(context.args[0])
            if ref_from_link != user_id and referrer_id is None and verified == 0:
                update_user_db(user_id, referrer_id=ref_from_link)
                ref_bal, ref_earn, ref_cnt, ref_ref, ref_ver = get_user(ref_from_link)
                update_user_db(ref_from_link, referrals_count=ref_cnt + 1)
        except ValueError:
            pass

    if verified == 1:
        with open("pic.jpg", "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="კეთილი იყოს თქვენი მობრძანება სკუბის ბოტზე.\nhttp://scoobys.cc",
                reply_markup=main_menu(user_id),
            )
        return

    emojis = ["🏮", "🔒", "💥", "📷", "🐥", "🔭", "💐", "✨", "🦖", "📦"]
    target = random.choice(emojis)
    context.user_data["captcha_target"] = target
    
    board_emojis = emojis.copy()
    random.shuffle(board_emojis)
    
    buttons = []
    row = []
    for emoji in board_emojis:
        row.append(InlineKeyboardButton(emoji, callback_data=f"cap_{emoji}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await update.message.reply_text(
        f"Solve this easy captcha\n\nChoose the correct EMOJI: {target}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def set_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("თქვენ არ გაქვთ ადმინისტრატორის უფლებები! ❌")
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("გამოყენების წესი: `/setbal username თანხა` ან `/addbal username თანხა`\nმაგალითად: `/setbal giorgi123 50`", parse_mode="Markdown")
        return

    try:
        target_username = args[0].strip().lstrip('@')
        amount = float(args[1])
        
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (target_username,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            await update.message.reply_text(f"❌ მომხმარებელი უსერნამით `@{target_username}` ბაზაში ვერ მოიძებნა!\n*(მომხმარებელმა ჯერ უნდა გაიაროს /start ბოტში)*", parse_mode="Markdown")
            return

        target_user_id = row[0]
        update_user_db(target_user_id, balance=amount)
        
        await update.message.reply_text(f"წარმატებით შეიცვალა! მომხმარებლის (`@{target_username}`, ID: {target_user_id}) ახალი ბალანსი: {amount} ₾ ✅")
    except ValueError:
        await update.message.reply_text("გთხოვთ მიუთითოთ სწორი ციფრები თანხისთვის!")


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    username = user.username
    data = query.data

    if data.startswith("cap_"):
        chosen_emoji = data.replace("cap_", "", 1)
        target = context.user_data.get("captcha_target")

        if chosen_emoji == target:
            update_user_db(user_id, verified=1, balance=None)
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            conn.commit()
            conn.close()

            await query.answer("კაპჩა წარმატებით გაიარეთ! ✅", show_alert=True)
            try:
                await query.message.delete()
            except Exception:
                pass
            with open("pic.jpg", "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption="კეთილი იყოს თქვენი მობრძანება სკუბის ბოტზე.\nhttp://scoobys.cc",
                    reply_markup=main_menu(user_id),
                )
        else:
            await query.answer("არასწორია! სცადე თავიდან ❌", show_alert=True)
        return

    async def show_page(caption_text, reply_markup, photo_filename="pic.jpg"):
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            with open(photo_filename, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=caption_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except FileNotFoundError:
            with open("pic.jpg", "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=caption_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

    back_button = [[InlineKeyboardButton("⬅️ Back", callback_data="home")]]

    if data == "home":
        await show_page(
            "კეთილი იყოს თქვენი მობრძანება სკუბის ბოტზე.\nhttp://scoobys.cc",
            main_menu(user_id)
        )

    # ==================== ადმინ პანელი ====================
    elif data == "admin_panel":
        if user_id not in ADMIN_IDS:
            await query.answer("არ გაქვთ ადმინისტრატორის უფლებები! ❌", show_alert=True)
            return
        admin_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 კატეგორიების მართვა", callback_data="admin_products_menu")],
            [InlineKeyboardButton("📍 უბნების მართვა", callback_data="admin_districts_menu")],
            [InlineKeyboardButton("🔗 პროდუქტის მიბმა უბანზე", callback_data="admin_link_prod_dist")],
            [InlineKeyboardButton("🖼️ სტოკისთვის ფოტოს დამატება", callback_data="admin_select_photo_prod")],
            [InlineKeyboardButton("📢 მესიჯის გაგზავნა ყველას", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📊 სტატისტიკა", callback_data="admin_stats")],
            [InlineKeyboardButton("⬅️ Back", callback_data="home")]
        ])
        await show_page("⚙️ **ადმინ პანელი:**\n\nაირჩიეთ სასურველი განყოფილება:", admin_markup)

    # --- კატეგორიების ქვემენიუ ---
    elif data == "admin_products_menu":
        if user_id not in ADMIN_IDS:
            return
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ კატეგორიის დამატება", callback_data="admin_add_product")],
            [InlineKeyboardButton("❌ კატეგორიის წაშლა", callback_data="admin_del_product_start")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
        await show_page("📦 **კატეგორიების (პროდუქტების) მართვა:**", markup)

    elif data == "admin_add_product":
        if user_id not in ADMIN_IDS:
            return
        context.user_data["admin_state"] = "waiting_for_new_product"
        await query.message.reply_text("📦 **ახალი კატეგორიის დამატება**\n\nგამოაგზავნეთ სახელი და ფასი შემდეგი ფორმატით:\n`კატეგორიის სახელი | ფასი`\n*(მაგალითად: Meow 0.5 | 155)*", parse_mode="Markdown")

    elif data == "admin_del_product_start":
        if user_id not in ADMIN_IDS:
            return
        products_map, _ = get_all_products()
        if not products_map:
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_products_menu")]])
            await show_page("❌ წასაშლელი კატეგორიები არ მოიძებნა.", back_markup)
            return
        
        prod_buttons = [[InlineKeyboardButton(f"❌ {name}", callback_data=f"del_prod_{key}")] for key, name in products_map.items()]
        prod_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_products_menu")])
        await show_page("❌ **აირჩიეთ კატეგორია წასაშლელად:**\n*(ყურადღება: წაიშლება ასევე მასთან დაკავშირებული მარაგები და კავშირები)*", InlineKeyboardMarkup(prod_buttons))

    elif data.startswith("del_prod_"):
        if user_id not in ADMIN_IDS:
            return
        p_key = data.replace("del_prod_", "")
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products WHERE product_key = ?", (p_key,))
        cursor.execute("DELETE FROM product_districts WHERE product_key = ?", (p_key,))
        cursor.execute("DELETE FROM stock_items WHERE product_key = ?", (p_key,))
        conn.commit()
        conn.close()

        await query.answer("კატეგორია წარმატებით წაიშალა! ✅", show_alert=True)
        
        products_map, _ = get_all_products()
        prod_buttons = [[InlineKeyboardButton(f"❌ {name}", callback_data=f"del_prod_{key}")] for key, name in products_map.items()]
        prod_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_products_menu")])
        await show_page("❌ **აირჩიეთ კატეგორია წასაშლელად:**", InlineKeyboardMarkup(prod_buttons))

    # --- უბნების ქვემენიუ ---
    elif data == "admin_districts_menu":
        if user_id not in ADMIN_IDS:
            return
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ უბნის დამატება", callback_data="admin_add_district")],
            [InlineKeyboardButton("❌ უბნის წაშლა", callback_data="admin_del_district_start")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]
        ])
        await show_page("📍 **უბნების მართვა:**", markup)

    elif data == "admin_add_district":
        if user_id not in ADMIN_IDS:
            return
        context.user_data["admin_state"] = "waiting_for_new_district"
        await query.message.reply_text("📍 **ახალი უბნის დამატება**\n\nგამოაგზავნეთ უბნის სახელი ტექსტურად (მაგალითად: `Vake`):", parse_mode="Markdown")

    elif data == "admin_del_district_start":
        if user_id not in ADMIN_IDS:
            return
        districts_map = get_all_districts()
        if not districts_map:
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_districts_menu")]])
            await show_page("❌ წასაშლელი უბნები არ მოიძებნა.", back_markup)
            return

        dist_buttons = [[InlineKeyboardButton(f"❌ {name}", callback_data=f"del_dist_{key}")] for key, name in districts_map.items()]
        dist_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_districts_menu")])
        await show_page("❌ **აირჩიეთ უბანი წასაშლელად:**\n*(ყურადღება: წაიშლება ყველა მარაგი ამ უბნიდან)*", InlineKeyboardMarkup(dist_buttons))

    elif data.startswith("del_dist_"):
        if user_id not in ADMIN_IDS:
            return
        d_key = data.replace("del_dist_", "")
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM districts WHERE district_key = ?", (d_key,))
        cursor.execute("DELETE FROM product_districts WHERE district_key = ?", (d_key,))
        cursor.execute("DELETE FROM stock_items WHERE district_key = ?", (d_key,))
        conn.commit()
        conn.close()

        await query.answer("უბანი წარმატებით წაიშალა! ✅", show_alert=True)

        districts_map = get_all_districts()
        dist_buttons = [[InlineKeyboardButton(f"❌ {name}", callback_data=f"del_dist_{key}")] for key, name in districts_map.items()]
        dist_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_districts_menu")])
        await show_page("❌ **აირჩიეთ უბანი წასაშლელად:**", InlineKeyboardMarkup(dist_buttons))

    elif data == "admin_link_prod_dist":
        if user_id not in ADMIN_IDS:
            return
        products_map, _ = get_all_products()
        prod_buttons = [[InlineKeyboardButton(p_name, callback_data=f"link_p_{p_key}")] for p_key, p_name in products_map.items()]
        prod_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])
        await show_page("🔗 **აირჩიეთ პროდუქტი**, რომელსაც უბანი უნდა მიაბათ:", InlineKeyboardMarkup(prod_buttons))

    elif data.startswith("link_p_"):
        if user_id not in ADMIN_IDS:
            return
        p_key = data.replace("link_p_", "")
        context.user_data["link_product_key"] = p_key
        
        districts_map = get_all_districts()
        dist_buttons = [InlineKeyboardButton(d_name, callback_data=f"link_d_{d_key}") for d_key, d_name in districts_map.items()]
        keyboard = chunk_buttons(dist_buttons, 2)
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_link_prod_dist")])
        await show_page("📍 **აირჩიეთ უბანი**, სადაც ეს პროდუქტი უნდა დაემატოს:", InlineKeyboardMarkup(keyboard))

    elif data.startswith("link_d_"):
        if user_id not in ADMIN_IDS:
            return
        d_key = data.replace("link_d_", "")
        p_key = context.user_data.get("link_product_key")
        
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO product_districts VALUES (?, ?)", (p_key, d_key))
            conn.commit()
            success = True
        except Exception:
            success = False
        conn.close()
        
        products_map, _ = get_all_products()
        districts_map = get_all_districts()
        p_name = products_map.get(p_key, p_key)
        d_name = districts_map.get(d_key, d_key)
        
        msg = f"✅ წარმატებით მიება პროდუქტი (**{p_name}**) უბანს (**{d_name}**)!" if success else "⚠️ ეს კავშირი უკვე არსებობს!"
        back_admin = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
        await show_page(msg, back_admin)

    elif data == "admin_select_photo_prod":
        if user_id not in ADMIN_IDS:
            return
        products_map, _ = get_all_products()
        photo_prod_buttons = [[InlineKeyboardButton(f"📦 {name}", callback_data=f"upload_prod_{key}")] for key, name in products_map.items()]
        photo_prod_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])
        
        await show_page("🖼️ **აირჩიეთ პროდუქტი**, რომლისთვისაც გსურთ ფოტოს/ლოკაციის დამატება:", InlineKeyboardMarkup(photo_prod_buttons))

    elif data.startswith("upload_prod_"):
        if user_id not in ADMIN_IDS:
            return
        prod_key = data.replace("upload_prod_", "")
        context.user_data["admin_upload_prod_key"] = prod_key
        
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT D.district_key, D.name FROM product_districts PD
            JOIN districts D ON PD.district_key = D.district_key
            WHERE PD.product_key = ?
        """, (prod_key,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            back_admin = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_select_photo_prod")]])
            await show_page("❌ ამ პროდუქტს ჯერ არცერთი უბანი არ აქვს მიბმული! ჯერ მიაბათ უბანზე.", back_admin)
            return

        dist_buttons = [InlineKeyboardButton(d_name, callback_data=f"upload_dist_{prod_key}_{d_key}") for d_key, d_name in rows]
        keyboard = chunk_buttons(dist_buttons, 2)
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_select_photo_prod")])

        await show_page("📍 **აირჩიეთ უბანი** ამ პროდუქტისთვის:", InlineKeyboardMarkup(keyboard))

    elif data.startswith("upload_dist_"):
        if user_id not in ADMIN_IDS:
            return
        remainder = data.replace("upload_dist_", "")
        idx = remainder.rfind("_dist_")
        prod_key = remainder[:idx]
        district_key = remainder[idx+1:]
        
        context.user_data["admin_upload_prod_key"] = prod_key
        context.user_data["admin_upload_dist_key"] = district_key
        context.user_data["admin_state"] = "waiting_for_stock_photo"
        
        products_map, _ = get_all_products()
        districts_map = get_all_districts()
        prod_name = products_map.get(prod_key, prod_key)
        dist_name = districts_map.get(district_key, district_key)
        await query.message.reply_text(f"📸 გამოაგზავნეთ ფოტო პროდუქტისთვის: **{prod_name}** | უბანი: **{dist_name}**\n*(ეს ფოტო ჩაჯდება მარაგში და გაიყიდება მხოლოდ ერთხელ)*", parse_mode="Markdown")

    elif data == "admin_broadcast":
        if user_id not in ADMIN_IDS:
            return
        context.user_data["admin_state"] = "waiting_for_broadcast"
        await query.message.reply_text("📢 **გამოაგზავნეთ მესიჯი (ტექსტი)**, რომელიც უნდა გაეგზავნოს ბოტის ყველა მომხმარებელს:", parse_mode="Markdown")

    elif data == "admin_stats":
        if user_id not in ADMIN_IDS:
            return
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM purchases")
        total_purchases = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(price) FROM purchases")
        total_revenue = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT COUNT(*) FROM stock_items")
        total_stock = cursor.fetchone()[0]
        conn.close()

        stats_text = (
            f"📊 **ბოტის სტატისტიკა:**\n\n"
            f"👥 სულ მომხმარებელი: `{total_users}`\n"
            f"🛒 სულ შენაძენი: `{total_purchases}`\n"
            f"📦 აქტიური მარაგი (ფოტოები): `{total_stock}` ცალი\n"
            f"💰 სულ ბრუნვა: `{total_revenue} ₾`"
        )
        back_admin = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
        await show_page(stats_text, back_admin)

    # ==================== ყიდვის და მენიუს ლოგიკა ====================
    elif data == "select_city":
        await show_page(
            "🏙️ Select City:",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Tbilisi", callback_data="city_tbilisi"),
                    InlineKeyboardButton("Batumi 🏖️", callback_data="city_batumi")
                ],
                [
                    InlineKeyboardButton("⬅️ Back", callback_data="home")
                ]
            ])
        )

    elif data == "city_tbilisi":
        products_map, products_prices = get_all_products()
        prod_buttons = [[InlineKeyboardButton(p_name, callback_data=p_key)] for p_key, p_name in products_map.items()]
        prod_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="select_city")])

        await show_page(
            "You have selected a city: Tbilisi\n\nProduct selection:",
            InlineKeyboardMarkup(prod_buttons)
        )

    elif data == "city_batumi":
        await show_page(
            "You have selected a city: Batumi\n\nProduct selection:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("ეს ქალაქი სამწუხაროდ ცარიელია :( ", callback_data="empty_batumi")],
                [InlineKeyboardButton("⬅️ Back", callback_data="select_city")]
            ])
        )

    elif data.startswith("prod_"):
        products_map, _ = get_all_products()
        if data in products_map:
            context.user_data["selected_product_key"] = data
            product_name = products_map[data]
            context.user_data["selected_product"] = product_name
            
            district_buttons = get_product_districts(data)
            district_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="city_tbilisi")])

            await show_page(
                f"You have selected a product\n\n🏠 City: Tbilisi\n\n🛒 Product: {product_name}\n\nSelect a district",
                InlineKeyboardMarkup(district_buttons)
            )

    elif data.startswith("dist_"):
        district_key = data.replace("dist_", "")
        districts_map = get_all_districts()
        district_name = districts_map.get(district_key, "District")
        
        context.user_data["selected_district_key"] = district_key
        context.user_data["selected_district"] = district_name
        
        product_key = context.user_data.get("selected_product_key")
        products_map, products_prices = get_all_products()
        product_name = products_map.get(product_key, "პროდუქტი")
        
        gel_price = float(products_prices.get(product_key, 0.0))
        ltc_amount = get_ltc_amount(gel_price)
        context.user_data["current_ltc"] = ltc_amount
        
        bal, _, _, _, _ = get_user(user_id)

        payment_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"LTC to be paid: {ltc_amount}", callback_data="pay_crypto")],
            [InlineKeyboardButton("💳 ბალანსით გადახდა", callback_data="buy_from_balance")],
            [InlineKeyboardButton("⬅️ Back", callback_data=product_key)]
        ])

        await show_page(
            f"You have selected a District: {district_name}\n\n🏠 City: Tbilisi\n🎯 District: {district_name}\n\n🛒 Product: {product_name}\n\n💰 Your Balance: {bal} ₾\n\n👑 Select a payment method: 👑",
            payment_markup
        )

    elif data == "buy_from_balance":
        try:
            product_key = context.user_data.get("selected_product_key")
            district_key = context.user_data.get("selected_district_key")
            
            if not product_key or not district_key:
                await query.message.reply_text("❌ მონაცემები ვერ მოიძებნა (შესაძლოა ბოტი გადატვირთულია). გთხოვთ თავიდან აირჩიოთ ქალაქი და პროდუქტი.")
                return

            products_map, products_prices = get_all_products()
            price = float(products_prices.get(product_key, 0.0))
            bal, earn, r_cnt, r_ref, r_ver = get_user(user_id)

            if bal < price:
                await query.message.reply_text(f"❌ არ გაქვთ საკმარისი ბალანსი! თქვენი ბალანსია: {bal} ₾, ხოლო პროდუქტი ღირს: {price} ₾.")
                return

            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, photo_path FROM stock_items WHERE product_key = ? AND district_key = ? LIMIT 1", (product_key, district_key))
            stock_item = cursor.fetchone()

            if not stock_item:
                conn.close()
                await query.message.reply_text("❌ სამწუხაროდ, ამ უბანზე მარაგი (სტოკი) ამოიწურა ან არ არის დამატებული ადმინის მიერ!")
                return

            stock_id, photo_path = stock_item

            cursor.execute("DELETE FROM stock_items WHERE id = ?", (stock_id,))
            conn.commit()
            conn.close()

            new_balance = round(float(bal - price), 2)
            update_user_db(user_id, balance=new_balance)

            if r_ref is not None:
                bonus = round(float(price * 0.02), 2)
                ref_bal, ref_earn, ref_cnt, ref_ref_id, ref_ver = get_user(r_ref)
                update_user_db(r_ref, balance=ref_bal + bonus, earned=ref_earn + bonus)

            product_name = products_map.get(product_key, "პროდუქტი")
            districts_map = get_all_districts()
            district_name = districts_map.get(district_key, "District")
            current_date = datetime.datetime.now().strftime("%d/%m/%Y")

            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO purchases (user_id, product_name, district, price, date, photo_path) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, product_name, district_name, price, current_date, photo_path)
            )
            purchase_id = cursor.lastrowid
            conn.commit()
            conn.close()

            success_text = (
                f"Your order №{purchase_id}\n\n"
                f"🏠 City: Tbilisi 🏙️\n"
                f"🎯 Area: {district_name}\n\n"
                f"🛒 Product: {product_name} {price}₾"
            )
            success_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Dispute 👨‍🎓", callback_data=f"dispute_{purchase_id}"),
                    InlineKeyboardButton("Review 👍", callback_data=f"review_{purchase_id}")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="history")]
            ])
            await show_page(success_text, success_markup, photo_filename=photo_path)
        except Exception as e:
            logging.error(f"Error in buy_from_balance: {e}")
            await query.message.reply_text(f"❌ შეცდომა ყიდვისას: {e}")

    elif data == "pay_crypto":
        ltc_amount = context.user_data.get("current_ltc", 0.0)
        
        payment_info_text = (
            f"💳 Coin: LTC\n\n"
            f"🏧 PAY FOR ORDER: 🏧\n"
            f"Send exact amount: *{ltc_amount} LTC*\n\n"
            f"To wallet address:\n`{LTC_WALLET}`\n\n"
            f"🤖 Payment will be processed automatically within a few minutes"
        )

        back_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="city_tbilisi")]
        ])
        await show_page(payment_info_text, back_markup, photo_filename="qr_code.jpg")

    elif data == "balance":
        bal, _, _, _, _ = get_user(user_id)
        balance_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Litecoin", callback_data="topup_ltc")],
            [InlineKeyboardButton("⬅️ Back", callback_data="home")]
        ])

        await show_page(
            f"Your Balance: {bal} ₾\n\nTop up balance:",
            balance_markup
        )

    elif data == "topup_ltc":
        topup_text = (
            f"💳 Coin: LTC\n\n"
            f"🏧 TOP UP YOUR BALANCE: 🏧\n"
            f"Pay any amount to the wallet:\n\n"
            f"`{LTC_WALLET}`\n\n"
            f"🤖 Payment will be processing automatically within a few minutes"
        )
        back_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="balance")]
        ])
        await show_page(topup_text, back_markup, photo_filename="qr_code.jpg")

    elif data == "history":
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, product_name, price, date FROM purchases WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await show_page("📦 თქვენი შეკვეთების ისტორია ცარიელია.", InlineKeyboardMarkup(back_button))
        else:
            history_buttons = []
            for p_id, p_name, p_price, p_date in rows:
                btn_text = f"{p_date} - {p_name} {p_price}₾"
                history_buttons.append([InlineKeyboardButton(btn_text, callback_data=f"hist_item_{p_id}")])
            
            history_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="home")])
            
            await show_page("🎁 Your purchases 🎁", InlineKeyboardMarkup(history_buttons), photo_filename="pic.jpg")

    elif data.startswith("hist_item_"):
        p_id = data.replace("hist_item_", "")
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, district, price, date, photo_path FROM purchases WHERE id = ? AND user_id = ?", (p_id, user_id))
        row = cursor.fetchone()
        conn.close()

        if not row:
            await query.answer("❌ შენაძენი ვერ მოიძებნა!", show_alert=True)
            return

        p_name, dist, p_price, _, photo_path = row
        
        detail_text = (
            f"Your order №{p_id}\n\n"
            f"🏠 City: Tbilisi 🏙️\n"
            f"🎯 Area: {dist}\n\n"
            f"🛒 Product: {p_name} {p_price}₾"
        )
        detail_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Dispute 👨‍🎓", callback_data=f"dispute_{p_id}"),
                InlineKeyboardButton("Review 👍", callback_data=f"review_{p_id}")
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="history")]
        ])
        
        if photo_path and os.path.exists(photo_path):
            await show_page(detail_text, detail_markup, photo_filename=photo_path)
        else:
            await show_page(detail_text, detail_markup, photo_filename="pic.jpg")

    elif data.startswith("dispute_"):
        p_id = data.replace("dispute_", "")
        await query.answer(f"⚠️ შეკვეთა №{p_id} - Dispute გახსნილია. ადმინისტრატორი მალე გიპასუხებთ.", show_alert=True)

    elif data.startswith("review_"):
        p_id = data.replace("review_", "")
        await query.answer(f"👍 მადლობა შეფასებისთვის (შეკვეთა №{p_id})!", show_alert=True)

    elif data == "referral":
        bal, earn, ref_count, r_ref, r_ver = get_user(user_id)
        bot_username = context.bot.username or "scooby666_bot"
        ref_link = f"https://t.me/{bot_username}?start={user_id}"

        referral_text = (
            f"Referrals: {ref_count}\n"
            f"Earned: {earn} ₾\n\n"
            f"When you refer new users to our bot (using a unique link)\n"
            f"Money will be automatically added to your balance: 2.0% from each purchase of referred customers\n\n"
            f"Your link to share with your friends to connect to the referral system: {ref_link}"
        )

        await show_page(
            referral_text,
            InlineKeyboardMarkup(back_button)
        )

# ==================== ადმინის შეტყობინებების მკაცრად იზოლირებული დამუშავება ====================
async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    state = context.user_data.get("admin_state")

    # 1. ახალი პროდუქტის (კატეგორიის) დამატება
    if state == "waiting_for_new_product":
        if update.message.text:
            text = update.message.text.strip()
            if "|" not in text:
                await update.message.reply_text("❌ არასწორი ფორმატი! გამოიყენეთ: `სახელი | ფასი`", parse_mode="Markdown")
                return
            
            parts = text.split("|")
            p_name = parts[0].strip()
            try:
                p_price = float(parts[1].strip())
            except ValueError:
                await update.message.reply_text("❌ ფასი უნდა იყოს რიცხვი!")
                return
            
            p_key = f"prod_{int(datetime.datetime.now().timestamp())}"
            
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("INSERT INTO products (product_key, name, price) VALUES (?, ?, ?)", (p_key, p_name, p_price))
            conn.commit()
            conn.close()
            
            context.user_data["admin_state"] = None
            
            next_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 ახლავე მიბმა უბანზე", callback_data=f"link_p_{p_key}")],
                [InlineKeyboardButton("⚙️ ადმინ პანელი", callback_data="admin_panel")]
            ])
            
            await update.message.reply_text(
                f"✅ კატეგორია წარმატებით შეიქმნა!\n📦 სახელი: **{p_name}**\n💰 ფასი: **{p_price} ₾**\n\nახლა შეგიძლიათ მიაბათ ის სასურველ უბანზე:",
                reply_markup=next_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ გთხოვთ გამოაგზავნოთ ტექსტი ფორმატით: `სახელი | ფასი`", parse_mode="Markdown")
        return

    # 2. ახალი უბნის დამატება
    elif state == "waiting_for_new_district":
        if update.message.text:
            d_name = update.message.text.strip()
            d_key = f"dist_{int(datetime.datetime.now().timestamp())}"
            
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("INSERT INTO districts (district_key, name) VALUES (?, ?)", (d_key, d_name))
            conn.commit()
            conn.close()
            
            context.user_data["admin_state"] = None
            
            next_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ ადმინ პანელი", callback_data="admin_panel")]
            ])
            
            await update.message.reply_text(
                f"✅ უბანი წარმატებით დაემატა!\n📍 სახელი: **{d_name}**",
                reply_markup=next_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ გთხოვთ გამოაგზავნოთ უბნის სახელი ტექსტურად.")
        return

    # 3. სტოკის ფოტოს დამატება
    elif state == "waiting_for_stock_photo":
        if update.message.photo:
            prod_key = context.user_data.get("admin_upload_prod_key")
            district_key = context.user_data.get("admin_upload_dist_key")
            
            if prod_key and district_key:
                photo_file = await update.message.photo[-1].get_file()
                filename = f"stock_photos/{prod_key}_{district_key}_{int(datetime.datetime.now().timestamp())}.jpg"
                await photo_file.download_to_drive(filename)
                
                conn = sqlite3.connect("bot_database.db")
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO stock_items (product_key, district_key, photo_path) VALUES (?, ?, ?)",
                    (prod_key, district_key, filename)
                )
                conn.commit()
                conn.close()
                
                products_map, _ = get_all_products()
                districts_map = get_all_districts()
                prod_name = products_map.get(prod_key, prod_key)
                dist_name = districts_map.get(district_key, district_key)
                
                context.user_data["admin_state"] = None
                context.user_data["admin_upload_prod_key"] = None
                context.user_data["admin_upload_dist_key"] = None
                
                await update.message.reply_text(
                    f"✅ მარაგი წარმატებით დაემატა!\n"
                    f"📦 პროდუქტი: **{prod_name}**\n"
                    f"📍 უბანი: **{dist_name}**\n"
                    f"📁 ფაილი: `{filename}`",
                    parse_mode="Markdown"
                )
        else:
            await update.message.reply_text("❌ გთხოვთ ატვირთოთ და გამოაგზავნოთ ფოტო (სურათი)!")
        return

    # 4. Broadcast
    elif state == "waiting_for_broadcast":
        if update.message.text:
            broadcast_text = update.message.text
            context.user_data["admin_state"] = None

            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()
            conn.close()

            success_count = 0
            fail_count = 0

            for (u_id,) in all_users:
                try:
                    await context.bot.send_message(chat_id=u_id, text=broadcast_text)
                    success_count += 1
                except Exception:
                    fail_count += 1

            await update.message.reply_text(
                f"📢 **რასპროსტრანება დასრულდა!**\n\n"
                f"✅ წარმატებით გაიგზავნა: `{success_count}` მომხმარებელთან\n"
                f"❌ ვერ გაიგზავნა: `{fail_count}`",
                parse_mode="Markdown"
            )
        return

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN ვერ მოიძებნა! შეამოწმე .env ფაილი.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setbal", set_balance_command))
    app.add_handler(CommandHandler("addbal", set_balance_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, admin_message_handler))

    print("ბოტი წარმატებით გაეშვა!")
    app.run_polling()

if __name__ == "__main__":
    main()