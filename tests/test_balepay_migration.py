"""Verify the gateway upgrade preserves existing account and gateway data."""
import unittest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from migrations import upgrade


class BalePayMigrationTests(unittest.TestCase):
    def test_existing_gateway_and_accounts_survive_repeated_upgrade(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        db = SQLAlchemy(app)
        with app.app_context():
            with db.engine.begin() as connection:
                connection.execute(text('CREATE TABLE balepay_gateway_config (id INTEGER PRIMARY KEY, wordpress_url TEXT, encrypted_secret TEXT)'))
                connection.execute(text("INSERT INTO balepay_gateway_config VALUES (1, 'https://payment.example.com', 'existing-ciphertext')"))
                connection.execute(text('CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT, status TEXT, traffic_limit INTEGER, traffic_usage FLOAT, traffic_used BIGINT, expire_date TEXT)'))
                connection.execute(text("INSERT INTO user VALUES (1, 'existing-user', 'active', 100, 79.308, 85156495920, '2029-01-01')"))
            for _ in range(2):
                upgrade(db)
            self.assertIn('encrypted_payment_settings', {c['name'] for c in inspect(db.engine).get_columns('balepay_gateway_config')})
            with db.engine.connect() as connection:
                self.assertEqual(tuple(connection.execute(text('SELECT wordpress_url, encrypted_secret, encrypted_payment_settings FROM balepay_gateway_config')).one()), ('https://payment.example.com', 'existing-ciphertext', ''))
                self.assertEqual(tuple(connection.execute(text('SELECT status, traffic_limit, traffic_usage, traffic_used, expire_date FROM user')).one()), ('active', 100, 79.308, 85156495920, '2029-01-01'))
