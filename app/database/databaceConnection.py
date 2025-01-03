from flask import Flask
import pymongo

class DatabaseConnection:
    def __init__(self):
        self.mango = pymongo(Flask(__name__))

    def Collection(self):
        self.users_collection = self.mango.db.users
        self.logins_collection = self.mango.db.logins
        self.orders_collection = self.mango.db.orders
        self.barcodes_collection = self.mango.db.barcodes
        self.barcode_images_collection = self.mango.db.barcode_images
        self.charges_collection = self.mango.db.charges
        self.stage1_collection = self.mango.db.stage1
        self.stage2_collection = self.mango.db.stage2
        self.stage3_collection = self.mango.db.stage3
        self.stage4_collection = self.mango.db.stage4
        self.stage5_collection = self.mango.db.stage5
        self.stage6_collection = self.mango.db.stage6