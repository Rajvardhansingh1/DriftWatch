"""Two families of fake LLM answers, so there is something real to drift between.

Family A: billing and subscription support answers. Family B: cooking tips. Each is built from templates with
many combinations, so no two responses are identical (a baseline of 200 identical sentences would say nothing).
Switching traffic from A to B is a deliberate, large distribution shift.
"""

import random

A_OPEN = [
    "Thanks for reaching out about your invoice.",
    "I can help with your subscription question.",
    "Happy to look into that charge for you.",
    "Good question about your billing details.",
    "Let me explain how your account charges work.",
]
A_BODY = [
    "Your {plan} plan renews on the {day} of each month and the next payment will be {amount}.",
    "A refund for the {plan} plan is processed within {n} business days after it is approved.",
    "You can update the card on file from the billing page under account settings.",
    "Invoices are emailed on the {day} and can be downloaded as a PDF from the dashboard.",
    "Downgrading from the {plan} plan takes effect at the end of the current billing period.",
    "The {amount} charge on your statement is the monthly fee for the {plan} plan.",
    "Failed payments are retried {n} times over the following week before the account is paused.",
    "Tax is added at checkout based on your billing address, and shows as a separate line on the invoice.",
]
A_CLOSE = [
    "Let me know if anything looks off on your statement.",
    "Reply here if you would like me to apply a credit.",
    "I can also send you a copy of the latest invoice.",
    "Tell me if you want to change the billing date.",
]
PLANS = ["Starter", "Team", "Business", "Enterprise", "Basic", "Pro"]
DAYS = ["1st", "5th", "10th", "15th", "20th", "28th"]
AMOUNTS = ["$19", "$29", "$49", "$99", "$149", "$299"]

B_OPEN = [
    "Here is a quick tip for tonight's dinner.",
    "A simple trick that makes a big difference in the kitchen.",
    "Try this the next time you cook at home.",
    "Chefs swear by this small technique.",
    "This is an easy way to get better flavour.",
]
B_BODY = [
    "Preheat the oven to {temp} degrees and roast the {veg} for {n} minutes until golden at the edges.",
    "Salt the {veg} generously and let it rest for {n} minutes before it goes into the hot pan.",
    "Toast the spices in a dry pan for a minute before adding the {veg}, and the whole dish smells richer.",
    "Simmer the sauce gently for {n} minutes, then finish it with a spoon of butter and fresh herbs.",
    "Rinse the rice until the water runs clear, then cook it with a lid for {n} minutes without peeking.",
    "Rest the meat for {n} minutes after cooking so the juices stay in the slices instead of on the board.",
    "Add a squeeze of lemon and a pinch of salt at the end to lift the flavour of the {veg}.",
    "Cut the {veg} into even pieces so everything cooks at the same speed in the pan.",
]
B_CLOSE = [
    "Taste as you go and adjust the seasoning at the end.",
    "Serve it warm with crusty bread.",
    "Leftovers keep well in the fridge for a couple of days.",
    "A handful of chopped parsley on top makes it look as good as it tastes.",
]
VEGS = ["carrots", "potatoes", "zucchini", "mushrooms", "cauliflower", "peppers", "onions", "broccoli"]
TEMPS = ["180", "200", "220", "230"]
NUMS = ["3", "5", "7", "10", "12", "15", "20"]

A_QUESTIONS = [
    "Why was I charged twice this month?",
    "How do I change the card on my account?",
    "When does my subscription renew?",
    "Can I get a refund for last month?",
    "How do I download my invoice?",
]
B_QUESTIONS = [
    "Any tip for crispy roasted vegetables?",
    "How do I stop rice from getting sticky?",
    "How long should I rest a steak?",
    "What makes a pan sauce taste richer?",
    "How do I season food properly?",
]


def make_response(family: str, rng: random.Random, marker: str = "") -> str:
    if family == "a":
        parts = [rng.choice(A_OPEN), rng.choice(A_BODY), rng.choice(A_CLOSE)]
    else:
        parts = [rng.choice(B_OPEN), rng.choice(B_BODY), rng.choice(B_CLOSE)]
    text = " ".join(parts).format(
        plan=rng.choice(PLANS), day=rng.choice(DAYS), amount=rng.choice(AMOUNTS),
        veg=rng.choice(VEGS), temp=rng.choice(TEMPS), n=rng.choice(NUMS),
    )
    return f"{text} {marker}".strip()


def make_prompt(family: str, rng: random.Random) -> str:
    return rng.choice(A_QUESTIONS if family == "a" else B_QUESTIONS)
