from services.benefits.app.api import partners, rewards
from shared.app import create_app
from shared.messaging import ConsumerSpec

app = create_app("benefits", routers=[partners.router, rewards.router], consumers=[
    ConsumerSpec("benefits", "rewards.requested", rewards.apply_rewards, transactional=True),
])
