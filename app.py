import os
from datetime import date
import re
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, render_template, request, redirect, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text, inspect

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "postgresql://dollarboost:boostsecure123@localhost:5432/dollarboost"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

WALLET_ADDRESS = "0x2c56Ebd1A0F51770e19d9b6E08d92D7ebb3cD8A2"
NETWORK = "BNB Smart Chain (BEP-20)"
MIN_WITHDRAWAL = Decimal("50.00")


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column("full_name", db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column("password_hash", db.String(255), nullable=False)
    balance = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Deposit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    tx_hash = db.Column(db.String(150), unique=True, nullable=False)
    network = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    user = db.relationship("User", backref="deposits")


class Withdrawal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    wallet = db.Column(db.String(100), nullable=False)
    network = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    payout_tx_hash = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    user = db.relationship("User", backref="withdrawals")



class Investment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    daily_reward = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    user = db.relationship("User", backref="investments")


class RewardClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    investment_id = db.Column(db.Integer, db.ForeignKey("investment.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    user = db.relationship("User", backref="reward_claims")
    investment = db.relationship("Investment", backref="claims")


class RewardPool(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    balance = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))


with app.app_context():
    db.create_all()
    if db.session.get(RewardPool, 1) is None:
        db.session.add(RewardPool(id=1, balance=Decimal("0.00")))
        db.session.commit()

    columns = [
        c["name"] for c in inspect(db.engine).get_columns("user")
    ]

    if "balance" not in columns:
        db.session.execute(text(
            'ALTER TABLE "user" ADD COLUMN balance NUMERIC(12,2) NOT NULL DEFAULT 0'
        ))
        db.session.commit()


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect("/admin/login")
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    return render_template("welcome.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not all([fullname, email, username, password]):
            flash("Please complete all fields.")
            return redirect("/register")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect("/register")

        existing = User.query.filter(
            (User.email == email) | (User.username == username)
        ).first()

        if existing:
            flash("Email or username already exists.")
            return redirect("/register")

        user = User(
            fullname=fullname,
            email=email,
            username=username,
            password=generate_password_hash(password)
        )

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please log in.")
        return redirect("/login")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect("/dashboard")

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])
    if not user:
        session.clear()
        return redirect("/login")

    deposits = Deposit.query.filter_by(
        user_id=user.id
    ).order_by(Deposit.created_at.desc()).all()

    withdrawals = Withdrawal.query.filter_by(
        user_id=user.id
    ).order_by(Withdrawal.created_at.desc()).all()

    investments = Investment.query.filter_by(
        user_id=user.id
    ).order_by(Investment.created_at.desc()).all()

    reward_claims = RewardClaim.query.filter_by(
        user_id=user.id
    ).order_by(RewardClaim.created_at.desc()).all()

    return render_template(
        "dashboard.html",
        user=user,
        deposits=deposits,
        withdrawals=withdrawals,
        investments=investments,
        reward_claims=reward_claims
    )


@app.route("/deposit", methods=["GET", "POST"])
def deposit():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        try:
            amount = Decimal(request.form.get("amount", "0"))
        except InvalidOperation:
            flash("Enter a valid USD amount.")
            return redirect("/deposit")

        tx_hash = request.form.get("tx_hash", "").strip()

        if not amount.is_finite() or amount < Decimal("1") or amount > Decimal("1000000"):
            flash("Enter a valid deposit amount.")
            return redirect("/deposit")

        if len(tx_hash) < 20 or len(tx_hash) > 150:
            flash("Enter your valid blockchain transaction hash.")
            return redirect("/deposit")

        if Deposit.query.filter_by(tx_hash=tx_hash).first():
            flash("This transaction hash has already been submitted.")
            return redirect("/deposit")

        record = Deposit(
            user_id=session["user_id"],
            amount=amount,
            tx_hash=tx_hash,
            network=NETWORK,
            status="Pending"
        )

        db.session.add(record)
        db.session.commit()

        flash("Deposit submitted for admin verification.")
        return redirect("/dashboard")

    return render_template(
        "deposit.html",
        wallet=WALLET_ADDRESS,
        network=NETWORK
    )


@app.route("/withdraw", methods=["GET", "POST"])
def withdraw():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect("/login")

    if request.method == "POST":
        try:
            amount = Decimal(request.form.get("amount", "0"))
        except InvalidOperation:
            flash("Enter a valid withdrawal amount.")
            return redirect("/withdraw")

        wallet = request.form.get("wallet", "").strip()

        if not amount.is_finite() or amount < MIN_WITHDRAWAL:
            flash("Minimum withdrawal is 50 USDT.")
            return redirect("/withdraw")

        if amount > Decimal("1000000"):
            flash("Enter a valid withdrawal amount.")
            return redirect("/withdraw")

        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet):
            flash("Enter a valid BNB Smart Chain wallet address.")
            return redirect("/withdraw")

        if (user.balance or Decimal("0.00")) < amount:
            flash("Insufficient available balance.")
            return redirect("/withdraw")

        # Reserve the requested amount while the admin reviews it.
        user.balance = user.balance - amount

        record = Withdrawal(
            user_id=user.id,
            amount=amount,
            wallet=wallet,
            network=NETWORK,
            status="Pending"
        )

        db.session.add(record)
        db.session.commit()

        flash("Withdrawal request submitted for admin review.")
        return redirect("/dashboard")

    return render_template(
        "withdraw.html",
        user=user,
        minimum=MIN_WITHDRAWAL,
        network=NETWORK
    )



@app.route("/invest", methods=["POST"])
def invest():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])
    if not user:
        session.clear()
        return redirect("/login")

    try:
        amount = Decimal(request.form.get("amount", "0"))
    except (InvalidOperation, TypeError):
        flash("Enter a valid investment amount.")
        return redirect("/dashboard")

    if not amount.is_finite() or amount < Decimal("100.00"):
        flash("Minimum investment is 100 USDT.")
        return redirect("/dashboard")

    if amount > Decimal("1000000.00"):
        flash("Investment amount is too high.")
        return redirect("/dashboard")

    if user.balance < amount:
        flash("Insufficient balance. Please deposit first.")
        return redirect("/dashboard")

    investment = Investment(
        user_id=user.id,
        amount=amount,
        daily_reward=(amount * Decimal("0.20")).quantize(Decimal("0.01")),
        status="Pending"
    )
    user.balance -= amount
    db.session.add(investment)
    db.session.commit()

    flash("Investment request submitted. Awaiting admin approval.")
    return redirect("/dashboard")


@app.route("/investment/claim/<int:investment_id>", methods=["POST"])
def claim_investment_reward(investment_id):
    if "user_id" not in session:
        return redirect("/login")

    investment = Investment.query.filter_by(
        id=investment_id,
        user_id=session["user_id"],
        status="Approved"
    ).first()

    if not investment:
        flash("Approved investment not found.")
        return redirect("/dashboard")

    today_claim = RewardClaim.query.filter(
        RewardClaim.investment_id == investment.id,
        db.func.date(RewardClaim.created_at) == date.today()
    ).first()

    if today_claim:
        flash("You have already claimed today's reward for this investment.")
        return redirect("/dashboard")

    user = db.session.get(User, session["user_id"])
    pool = db.session.get(RewardPool, 1)
    reward = investment.daily_reward

    if not user or not pool:
        flash("Reward service is currently unavailable.")
        return redirect("/dashboard")

    if pool.balance < reward:
        flash("The reward pool does not have enough funds. Please contact the administrator.")
        return redirect("/dashboard")

    pool.balance -= reward
    user.balance += reward

    db.session.add(RewardClaim(
        user_id=user.id,
        investment_id=investment.id,
        amount=reward,
        status="Approved"
    ))

    db.session.commit()

    flash(f"Success! {reward} USDT has been credited to your available balance.")
    return redirect("/dashboard")

@app.route("/admin/investment/<int:investment_id>/<action>", methods=["POST"])
@admin_required
def review_investment(investment_id, action):
    investment = db.session.get(Investment, investment_id)

    if not investment or investment.status != "Pending":
        flash("Pending investment not found.")
        return redirect("/admin")

    if action == "approve":
        investment.status = "Approved"
        flash("Investment approved.")
    elif action == "reject":
        user = db.session.get(User, investment.user_id)
        if user:
            user.balance += investment.amount
        investment.status = "Rejected"
        flash("Investment rejected and refunded.")
    else:
        flash("Invalid action.")
        return redirect("/admin")

    db.session.commit()
    return redirect("/admin")


@app.route("/admin/reward-pool/fund", methods=["POST"])
@admin_required
def fund_reward_pool():
    try:
        amount = Decimal(request.form.get("amount", "0"))
    except (InvalidOperation, TypeError):
        flash("Enter a valid amount.")
        return redirect("/admin")

    if not amount.is_finite() or amount <= 0:
        flash("Funding amount must be greater than zero.")
        return redirect("/admin")

    pool = db.session.get(RewardPool, 1)
    pool.balance += amount
    db.session.commit()
    flash("Reward pool funded.")
    return redirect("/admin")


@app.route("/admin/reward/<int:claim_id>/<action>", methods=["POST"])
@admin_required
def review_reward(claim_id, action):
    claim = db.session.get(RewardClaim, claim_id)

    if not claim or claim.status != "Pending":
        flash("Pending reward request not found.")
        return redirect("/admin")

    if action == "approve":
        pool = db.session.get(RewardPool, 1)
        if pool.balance < claim.amount:
            flash("Insufficient funds in the reward pool.")
            return redirect("/admin")

        user = db.session.get(User, claim.user_id)
        if not user:
            flash("User not found.")
            return redirect("/admin")

        pool.balance -= claim.amount
        user.balance += claim.amount
        claim.status = "Approved"
        flash("Reward approved and credited.")
    elif action == "reject":
        claim.status = "Rejected"
        flash("Reward request rejected.")
    else:
        flash("Invalid action.")
        return redirect("/admin")

    db.session.commit()
    return redirect("/admin")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin_username = "boostadmin"
        admin_password = "DBoost#2026!Secure"

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if not admin_username or not admin_password:
            flash("Admin credentials have not been configured.")
        elif username == admin_username and password == admin_password:
            session["is_admin"] = True
            return redirect("/admin")
        else:
            flash("Incorrect admin login.")

    return render_template("admin_login.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    deposits = Deposit.query.order_by(
        Deposit.created_at.desc()
    ).all()

    withdrawals = Withdrawal.query.order_by(
        Withdrawal.created_at.desc()
    ).all()

    total_users = User.query.count()
    pending = Deposit.query.filter_by(status="Pending").count()
    pending_withdrawals = Withdrawal.query.filter_by(
        status="Pending"
    ).count()

    return render_template(
        "admin.html",
        deposits=deposits,
        withdrawals=withdrawals,
        total_users=total_users,
        pending=pending,
        pending_withdrawals=pending_withdrawals,
        investments=Investment.query.order_by(
            Investment.created_at.desc()
        ).all(),
        pending_investments=Investment.query.filter_by(
            status="Pending"
        ).count(),
        reward_claims=RewardClaim.query.order_by(
            RewardClaim.created_at.desc()
        ).all(),
        pending_rewards=RewardClaim.query.filter_by(
            status="Pending"
        ).count(),
        reward_pool=db.session.get(RewardPool, 1)
    )


@app.route("/admin/deposit/<int:deposit_id>/<action>", methods=["POST"])
@admin_required
def review_deposit(deposit_id, action):
    record = db.session.get(Deposit, deposit_id)

    if not record:
        flash("Deposit not found.")
    elif record.status != "Pending":
        flash("This deposit has already been reviewed.")
    elif action == "approve":
        record.status = "Approved"
        user = db.session.get(User, record.user_id)
        user.balance = (user.balance or Decimal("0.00")) + record.amount
        db.session.commit()
        flash("Deposit approved and balance credited.")
    elif action == "reject":
        record.status = "Rejected"
        db.session.commit()
        flash("Deposit rejected.")
    else:
        flash("Invalid action.")

    return redirect("/admin")


@app.route("/admin/withdrawal/<int:withdrawal_id>/<action>", methods=["POST"])
@admin_required
def review_withdrawal(withdrawal_id, action):
    record = db.session.get(Withdrawal, withdrawal_id)

    if not record:
        flash("Withdrawal request not found.")
        return redirect("/admin")

    if record.status != "Pending":
        flash("This withdrawal has already been reviewed.")
        return redirect("/admin")

    user = db.session.get(User, record.user_id)

    if action == "reject":
        # Return reserved funds to the user's balance.
        user.balance = (user.balance or Decimal("0.00")) + record.amount
        record.status = "Rejected"
        db.session.commit()
        flash("Withdrawal rejected. Reserved funds returned.")

    elif action == "paid":
        payout_hash = request.form.get("payout_tx_hash", "").strip()

        if len(payout_hash) < 20 or len(payout_hash) > 150:
            flash("Enter the payout transaction hash before marking as paid.")
            return redirect("/admin")

        if Withdrawal.query.filter_by(payout_tx_hash=payout_hash).first():
            flash("That payout transaction hash is already recorded.")
            return redirect("/admin")

        record.payout_tx_hash = payout_hash
        record.status = "Paid"
        db.session.commit()
        flash("Withdrawal marked as paid.")

    else:
        flash("Invalid withdrawal action.")

    return redirect("/admin")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
