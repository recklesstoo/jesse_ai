from hypothesis import settings

settings.register_profile("ci", deadline=None, max_examples=25)
settings.load_profile("ci")
