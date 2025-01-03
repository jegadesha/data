from flask import Flask
app = Flask(__name__)
    
from app.controller.authController import *
from app.controller.orderController import *
from app.database.databaceConnection import *
