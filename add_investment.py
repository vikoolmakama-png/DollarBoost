from pathlib import Path
import re

p = Path("app.py")
s = p.read_text()

if "class Investment(db.Model)" in s:
    print("Investment models already exist. Stopping to avoid duplicates.")
    raise SystemExit

if '@app.route("/admin/login"' not in s:
    raise SystemExit("Admin login route not found. No changes made.")

# Import date
if "from datetime import date" not in s:
    s = s.replace("import os", "import os\nfrom datetime import date", 1)

# Add models before database initialization
marker = "with app.app_context():\n    db.create_all()"
models = '''
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


'''
if marker not in s:
    raise SystemExit("Database initialization not found. No changes made.")
s = s.replace(marker, models + marker, 1)

# Create reward pool after db.create_all()
s = s.replace(
    "    db.create_all()",
    '''    db.create_all()
    if db.session.get(RewardPool, 1) is None:
        db.session.add(RewardPool(id=1, balance=Decimal("0.00")))
        db.session.commit()''',
    1
)

# Add routes before admin login
routes = '''
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
        flash("A reward request has already been submitted today.")
        return redirect("/dashboard")

    db.session.add(RewardClaim(
        user_id=investment.user_id,
        investment_id=investment.id,
        amount=investment.daily_reward,
        status="Pending"
    ))
    db.session.commit()

    flash("Reward request submitted for admin review.")
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


'''
s = s.replace('@app.route("/admin/login"', routes + '@app.route("/admin/login"', 1)

# Pass investment information to dashboard
start = s.find('def dashboard():')
end = s.find('@app.route("/deposit"', start)
if start < 0 or end < 0:
    raise SystemExit("Could not locate dashboard function. No changes saved.")

part = s[start:end]
if "investments=Investment.query" not in part:
    part = re.sub(
        r'(\s+withdrawals=withdrawals,?\s*)\)',
        r'\1        investments=Investment.query.filter_by(user_id=user.id).order_by(Investment.created_at.desc()).all(),\n        reward_claims=RewardClaim.query.filter_by(user_id=user.id).order_by(RewardClaim.created_at.desc()).all()\n    )',
        part,
        count=1
    )
    if "investments=Investment.query" not in part:
        raise SystemExit("Could not update dashboard render arguments. No changes saved.")
    s = s[:start] + part + s[end:]

# Pass investment information to admin
start = s.find("def admin_dashboard():")
end = s.find('@app.route("/admin/deposit', start)
if start < 0 or end < 0:
    raise SystemExit("Could not locate admin dashboard. No changes saved.")

part = s[start:end]
if "pending_investments=" not in part:
    part = re.sub(
        r'(\s+pending_withdrawals=pending_withdrawals,?\s*)\)',
        r'\1        investments=Investment.query.order_by(Investment.created_at.desc()).all(),\n        pending_investments=Investment.query.filter_by(status="Pending").count(),\n        reward_claims=RewardClaim.query.order_by(RewardClaim.created_at.desc()).all(),\n        pending_rewards=RewardClaim.query.filter_by(status="Pending").count(),\n        reward_pool=db.session.get(RewardPool, 1)\n    )',
        part,
        count=1
    )
    if "pending_investments=" not in part:
        raise SystemExit("Could not update admin render arguments. No changes saved.")
    s = s[:start] + part + s[end:]

p.write_text(s)
print("Investment models and routes added.")
