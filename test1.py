from flask import Flask, request, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from flask_pymongo import PyMongo
import jwt
from datetime import datetime, timedelta
import random
import io
from barcode import EAN13
from barcode.writer import ImageWriter
from PIL import Image
from reportlab.pdfgen import canvas
import os
import base64

app = Flask(__name__)
app.config['MONGO_URI'] = 'mongodb://localhost:27017/florence'  # Replace with your MongoDB URI
app.config['SECRET_KEY'] = 'your_secret_key'  # Replace with your secret key

mongo = PyMongo(app)

# Define collections: users, logins, orders, and barcodes
users_collection = mongo.db.users
logins_collection = mongo.db.logins
orders_collection = mongo.db.orders
barcodes_collection = mongo.db.barcodes
barcode_images_collection = mongo.db.barcode_images

# Register a new user
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password are required!'}), 400

    user_exists = users_collection.find_one({'username': username})

    if user_exists:
        return jsonify({'message': 'User already exists!'}), 400

    hashed_password = generate_password_hash(password)

    users_collection.insert_one({
        'username': username,
        'password': hashed_password,
        'created_at': datetime.utcnow()
    })

    return jsonify({'message': 'User registered successfully!'}), 201


# User login
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password are required!'}), 400

    user = users_collection.find_one({'username': username})

    if not user or not check_password_hash(user['password'], password):
        return jsonify({'message': 'Invalid credentials!'}), 401

    # Generate JWT token for the session
    token = jwt.encode({
        'username': user['username'],
        'exp': datetime.utcnow() + timedelta(hours=1)
    }, app.config['SECRET_KEY'], algorithm='HS256')

    # Store login activity in the logins collection
    logins_collection.insert_one({
        'username': username,
        'login_time': datetime.utcnow(),
        'token': token
    })

    return jsonify({'token': token}), 200


# Auto-generate a 6-digit number for Sl.No.
def generate_sl_no():
    return random.randint(100000, 999999)


# Submit Order Details with size and quantity breakdown
@app.route('/submit_order', methods=['POST'])
def submit_order():
    data = request.get_json()

    # Extracting mandatory fields from request
    order_number = data.get('order_number')
    article_number = data.get('article_number')
    color = data.get('color')
    gender = data.get('gender')
    shoe_type = data.get('shoe_type')
    order_pairs = data.get('order_pairs')  # Total pairs ordered
    oef_number = data.get('oef_number')
    customer = data.get('customer')
    size_type = data.get('size_type')
    style = data.get('style')
    fit = data.get('fit')
    season = data.get('season')
    delivery_date = data.get('delivery_date')

    # Sizes and quantities should be a list of dictionaries, e.g., [{"size": "10", "quantity": 50}, {"size": "11", "quantity": 50}]
    sizes_quantities = data.get('sizes_quantities')

    # Check if all fields are provided
    if not all([order_number, article_number, color, gender, shoe_type, order_pairs, oef_number, customer, size_type, style, fit, season, delivery_date, sizes_quantities]):
        return jsonify({'message': 'All fields are mandatory!'}), 400

    # Ensure that sizes_quantities is a list and validate the quantity sum
    if not isinstance(sizes_quantities, list) or len(sizes_quantities) == 0:
        return jsonify({'message': 'Sizes and quantities must be provided!'}), 400

    total_quantity = sum([item.get('quantity', 0) for item in sizes_quantities])

    # Validate that the sum of quantities for all sizes matches the total order pairs
    if total_quantity != int(order_pairs):
        return jsonify({'message': f'Total quantity for all sizes ({total_quantity}) does not match order pairs ({order_pairs})!'}), 400

    # Ensure the order_number is 10 digits by padding with zeros if necessary
    order_number = str(order_number).zfill(10)

    # Generate a unique Sl.No.
    sl_no = generate_sl_no()

    # Store the order in MongoDB
    orders_collection.insert_one({
        'sl_no': sl_no,
        'order_number': order_number,
        'article_number': article_number,
        'color': color,
        'gender': gender,
        'shoe_type': shoe_type,
        'order_pairs': order_pairs,
        'oef_number': oef_number,
        'customer': customer,
        'size_type': size_type,
        'style': style,
        'fit': fit,
        'season': season,
        'delivery_date': delivery_date,
        'sizes_quantities': sizes_quantities,  # Store sizes and quantities here
        'created_at': datetime.utcnow()
    })

    return jsonify({'message': 'Order submitted successfully!', 'sl_no': sl_no}), 201


# Generate barcode number based on order number, shoe size, and serial number
def generate_barcode(order_number, shoe_size, serial_number):
    # Format order_number to be 10 digits (pad with zeros)
    order_number_formatted = str(order_number).zfill(10)

    # Format shoe_size (assuming it should contribute 3 digits; you can adjust this based on your requirement)
    shoe_size_formatted = str(int(float(shoe_size) * 10)).zfill(3)  # Example: '10.5' becomes '105'

    # Format serial_number to ensure it is the correct length to fit into the total of 16 digits
    serial_number_formatted = str(serial_number).zfill(3)  # 3 digits

    # Calculate the lengths of each part and ensure they add up to 16
    total_length = len(order_number_formatted) + len(shoe_size_formatted) + len(serial_number_formatted)

    # If total length is greater than 16, trim or adjust accordingly (custom logic may be needed based on specifics)
    if total_length > 16:
        raise ValueError("Combined length exceeds 16 digits.")

    # Calculate how many extra digits are needed to reach 16
    extra_digits_needed = 16 - total_length

    # Create the barcode
    barcode_number = f"{order_number_formatted}{shoe_size_formatted}{serial_number_formatted}"

    # If there's space left to fill, pad with zeros
    barcode_number += '0' * extra_digits_needed

    return barcode_number[:16]  # Ensure only the first 16 digits are returned


def create_barcode_image(barcode_number):
    # Generate barcode and save it to a BytesIO buffer
    barcode = EAN13(barcode_number, writer=ImageWriter())
    buffer = io.BytesIO()
    barcode.write(buffer)
    buffer.seek(0)
    return buffer.getvalue() #return buffer value 
# Create PDF with multiple barcode images
def create_pdf_with_barcodes(order_number, shoe_size, total_pairs):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)

    for serial_number in range(1, total_pairs + 1):
        barcode_number = generate_barcode(order_number, shoe_size, serial_number)
        barcode_img_buffer = create_barcode_image(barcode_number)

        # Save the buffer as a temporary image file
        with Image.open(barcode_img_buffer) as img:
            img.save(f'barcode_{barcode_number}.png')  # Save the image temporarily

            # Draw the barcode image in the PDF
            pdf.drawImage(f'barcode_{barcode_number}.png', 150, 650 - (serial_number - 1) * 150, width=100, height=145)

            # Add the last 12 digits of the barcode below the barcode image
            last_12_digits = barcode_number[-12:]
            pdf.setFont("Helvetica", 10)
            pdf.drawString(150, 650 - (serial_number - 1) * 150 - 15, f"{last_12_digits}")

            # Clean up the temporary image file
            # os.remove(f'barcode_{barcode_number}.png')

            # Check if we have reached the limit of 15 barcodes
            if serial_number % 15 == 0:
                pdf.showPage()  # Move to the next page

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer



# Generate barcodes and store them in MongoDB
@app.route('/generate_barcode', methods=['POST'])
def generate_barcode_route():
    data = request.get_json()
    order_number = data.get('order_number')

    if not order_number:
        return jsonify({'message': 'Order number is required!'}), 400

    # Find the order from the database
    order = orders_collection.find_one({'order_number': order_number})

    if not order:
        return jsonify({'message': 'Order not found!'}), 404

    sizes_quantities = order.get('sizes_quantities')
    if not sizes_quantities or len(sizes_quantities) == 0:
        return jsonify({'message': 'No sizes found for this order!'}), 400

    # Create a PDF buffer
    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer)

    # Variables for positioning
    y_position = 750  # Start from the top of the page
    x_position = 50   # Start from the left side
    barcode_count = 0  # Count barcodes to limit to 15 per page

    # Column and row settings
    columns = 4
    rows = 5
    barcode_width = 100
    barcode_height = 75
    spacing = 30  # Spacing between barcodes

    # Iterate through each size and generate barcodes
    for size_info in sizes_quantities:
        shoe_size = size_info.get('size')
        total_pairs = size_info.get('quantity')  # Use quantity for that size to generate barcodes

        # Generate barcodes for this size
        for serial_number in range(1, total_pairs + 1):
            barcode_number = generate_barcode(order_number, shoe_size, serial_number)

            # Create barcode image and convert it to binary data
            barcode_img_data = create_barcode_image(barcode_number)

            # Store the barcode details and image in MongoDB
            barcodes_collection.insert_one({
                'order_number': order_number,
                'shoe_size': shoe_size,
                'barcode_number': barcode_number,
                'serial_number': serial_number,
                'image_data': base64.b64encode(barcode_img_data).decode('utf-8'),  # Store as Base64 string
                'created_at': datetime.utcnow()
            })

            # Store the barcode image in the separate collection
            barcode_images_collection.insert_one({
                'barcode_number': barcode_number,
                'image_data': base64.b64encode(barcode_img_data).decode('utf-8'),  # Store as Base64 string
                'created_at': datetime.utcnow()
            })

            # Save the barcode image to a temporary file for PDF drawing
            image_path = f'barcode_{barcode_number}.png'
            with open(image_path, 'wb') as f:
                f.write(barcode_img_data)

            # Draw barcode image on the PDF
            pdf.drawImage(image_path, x_position, y_position, width=barcode_width, height=barcode_height)

            # # Add the last 12 digits below the barcode image
            # last_12_digits = barcode_number[-12:]
            # pdf.setFont("Helvetica", 10)
            # pdf.drawString(x_position, y_position - 15, f"{last_12_digits}")

            # Update positions
            x_position += barcode_width + spacing  # Move to the right for the next barcode
            barcode_count += 1  # Increment barcode count

            # If we have reached the end of a row
            if barcode_count % columns == 0:
                x_position = 50  # Reset x_position
                y_position -= (barcode_height + spacing)  # Move down for the next row

            # If we have reached the limit of 15 barcodes, create a new page
            if barcode_count % (columns * rows) == 0:
                pdf.showPage()  # Finalize the current page
                pdf.setFont("Helvetica", 10)  # Reset font
                x_position = 50  # Reset x_position for the new page
                y_position = 750  # Reset y_position for the new page

    # Finalize and save the PDF
    pdf.save()
    pdf_buffer.seek(0)

    # Return the PDF as a downloadable file
    return send_file(pdf_buffer, as_attachment=True, download_name=f"barcodes_{order_number}.pdf", mimetype='application/pdf')

# Start the Flask application
if __name__ == '__main__':
    app.run(debug=True)
