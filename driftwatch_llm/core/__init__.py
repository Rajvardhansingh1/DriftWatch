"""Pure detector code shared by the Render server (monitor/) and the local agent.

Nothing here imports monitor/, SQLAlchemy or the server settings. Modules that need numpy say so;
events, scoring, hallucination and backoff are standard-library only.
"""
