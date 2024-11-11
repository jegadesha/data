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
import base64
from datetime import datetime, timedelta
import pymongo

app = Flask(__name__)
app.config['MONGO_URI'] = 'mongodb://localhost:27017/florence'  # Replace with your MongoDB URI
app.config['SECRET_KEY'] = 'your_secret_key'  # Replace with your secret key

mongo = PyMongo(app)

# Define two separate collections: one for users and one for login activities
users_collection = mongo.db.users
logins_collection = mongo.db.logins
orders_collection = mongo.db.orders
barcodes_collection = mongo.db.barcodes
barcode_images_collection = mongo.db.barcode_images
charges_collection = mongo.db.charges
stage1_collection = mongo.db.stage1
stage2_collection = mongo.db.stage2
stage3_collection = mongo.db.stage3
stage4_collection = mongo.db.stage4
stage5_collection = mongo.db.stage5

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


# Create barcode image
def create_barcode_image(barcode_number):
    barcode = EAN13(barcode_number[4:], writer=ImageWriter())
    buffer = io.BytesIO()
    barcode.write(buffer)
    buffer.seek(0)
    # Convert the image to base64
    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return image_base64
# Create PDF with multiple barcode images
def create_pdf_with_barcodes(order_number, shoe_size, total_pairs):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)

    for serial_number in range(1, total_pairs + 1):
        barcode_number = generate_barcode(order_number, shoe_size, serial_number)
        barcode_img = create_barcode_image(barcode_number)

        # Convert image to Pillow Image and paste it in the PDF
        image = Image.open(barcode_img)
        # Positioning barcodes vertically
        pdf.drawInlineImage(image, 150, 650 - (serial_number - 1) * 150, width=100, height=145)

        # Add text details for each barcode
        pdf.setFont("Helvetica", 10)
        # pdf.drawString(50, 70 - (serial_number - 1) * 120, f"Order Number: {order_number}")
        # pdf.drawString(50, 70 - (serial_number - 1) * 120, f"Barcode: {barcode_number}")
        pdf.drawString(50, 70 - (serial_number - 1) * 120, f"Shoe Size: {shoe_size}")
        # Add the full 16-digit barcode below the barcode image
        
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer

# Route to generate and download barcodes as a single PDF and store barcode images in the database
# Route to generate and download barcodes as a single PDF and store barcode images in the database
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

    # Initial PDF position settings for 3 rows and 4 columns per page
    y_position = 750  # Start Y position for the first row (adjust for each new row)
    x_position = 70   # Start X position for the first column (adjust for each new column)
    barcode_width = 130  # Width of each barcode image
    barcode_height = 75  # Height of each barcode image
    row_count = 0  # Track rows
    col_count = 0  # Track columns

    # Iterate through each size and generate barcodes
    for size_info in sizes_quantities:
        shoe_size = size_info.get('size')
        total_pairs = size_info.get('quantity')  # Use quantity for that size to generate barcodes

        # Generate barcodes for this size
        for serial_number in range(1, total_pairs + 1):
            barcode_number = generate_barcode(order_number, shoe_size, serial_number)

            # Create barcode image as base64
            barcode_img_base64 = create_barcode_image(barcode_number)
            
            # Store the barcode image in MongoDB
            barcode_images_collection.insert_one({
                'order_number': order_number,
                'shoe_size': shoe_size,
                'barcode_number': barcode_number,
                'image': barcode_img_base64,  # Store base64 image
                'serial_number': serial_number,
                'created_at': datetime.utcnow()
            })

            # Decode the base64 image to display in PDF
            barcode_img = io.BytesIO(base64.b64decode(barcode_img_base64))
            image = Image.open(barcode_img)

            # Draw barcode image on the PDF
            pdf.drawInlineImage(image, x_position, y_position, width=barcode_width, height=barcode_height)

            # Add text details below the barcode image
            pdf.setFont("Helvetica", 12)
            pdf.drawString(x_position, y_position - 15, f"Shoe Size: {shoe_size}")
            pdf.drawString(x_position, y_position - 30, f"Barcode: {barcode_number}")

            # Update column count and x_position for the next barcode
            col_count += 1
            x_position += barcode_width + 50  # Move right for the next barcode column

            # If 4 columns are filled, reset x_position and move to the next row
            if col_count == 5:
                x_position = 70  # Reset x_position to the first column
                y_position -= barcode_height + 100  # Move down for the next row
                col_count = 0  # Reset column count
                row_count += 1  # Increase the row count

            # If 3 rows are filled, create a new page
            if row_count == 3:
                pdf.showPage()  # Finalize the current page
                pdf.setFont("Helvetica", 7)  # Reset font
                y_position = 750  # Reset y_position for the new page
                row_count = 0  # Reset row count

    # Finalize and save the PDF
    pdf.save()
    pdf_buffer.seek(0)

    # Return the PDF as a downloadable file
    return send_file(pdf_buffer, as_attachment=True, download_name=f"barcodes_{order_number}.pdf", mimetype='application/pdf')

# Charge route that starts a 45-minute timer based on barcode number
@app.route('/charge', methods=['POST'])
def charge():
    data = request.get_json()
    barcode_number = data.get('barcode_number')
    user_token = request.headers.get('Authorization')

    if not barcode_number:
        return jsonify({'message': 'Barcode number is required!'}), 400

    if not user_token:
        return jsonify({'message': 'User token is required!'}), 401

    # Verify JWT token to get user data
    try:
        decoded_token = jwt.decode(user_token, app.config['SECRET_KEY'], algorithms=['HS256'])
        username = decoded_token['username']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token!'}), 401

    # Find the order data based on the barcode number
    order_data = barcode_images_collection.find_one({'barcode_number': barcode_number})

    if not order_data:
        return jsonify({'message': 'Order not found for the given barcode number!'}), 404

    # Extract order details from the order_data
    order_number = order_data['order_number']
    shoe_size = order_data['shoe_size']

    # Start a 45-minute timer from the current time
    start_time = datetime.utcnow()
    end_time = start_time + timedelta(minutes=45)

    # Store the charge information in the charges collection
    charge_data = {
        'username': username,
        'barcode_number': barcode_number,
        'order_number': order_number,
        'shoe_size': shoe_size,
        'start_time': start_time,
        'end_time': end_time,
        'created_at': datetime.utcnow()
    }

    charges_collection.insert_one(charge_data)

    return jsonify({
        'message': 'Charge started successfully!',
        'barcode_number': barcode_number,
        'order_number': order_number,
        'username': username,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat()
    }), 201
@app.route('/stage1', methods=['POST'])
def stage1():
    data = request.get_json()
    barcode_number = data.get('barcode_number')
    user_token = request.headers.get('Authorization')

    if not barcode_number:
        return jsonify({'message': 'Barcode number is required!'}), 400

    if not user_token:
        return jsonify({'message': 'User token is required!'}), 401

    # Verify JWT token to get user data
    try:
        decoded_token = jwt.decode(user_token, app.config['SECRET_KEY'], algorithms=['HS256'])
        username = decoded_token['username']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token!'}), 401

    # Check if a completed charge exists for this barcode number
    charge_data = charges_collection.find_one({'barcode_number': barcode_number})
    
    if not charge_data:
        return jsonify({'message': 'Charge process for this barcode is not completed. Cannot proceed to Stage 1.'}), 400

    # Fetch the order number from the order collection based on the barcode number
    order_data = charges_collection.find_one({'barcode_number': barcode_number})

    if not order_data:
        return jsonify({'message': 'Order not found for the given barcode number!'}), 404

    order_number = order_data['order_number']

    # Get the last charge entry for this barcode from charges_collection to check timing
    last_charge = charges_collection.find_one(
        {'barcode_number': barcode_number},
        sort=[('created_at', pymongo.DESCENDING)]
    )

    if not last_charge:
        return jsonify({'message': 'No previous charge record found for the barcode!'}), 404

    # Calculate the elapsed time since the last charge
    current_time = datetime.utcnow()
    elapsed_time = current_time - last_charge['start_time']
    delay_minutes = (elapsed_time.total_seconds() / 60) - 45  # subtract the 45-minute allowed time

    # If elapsed time is over 45 minutes, mark it as delayed
    if elapsed_time > timedelta(minutes=45):
        delay_message = f"Delayed by {int(delay_minutes)} minutes"
    else:
        delay_message = "On time"

    # Set up data for the new timing in stage1 collection
    start_time = datetime.utcnow()
    end_time = start_time + timedelta(minutes=45)

    # Store this stage1 data in the stage1_collection
    stage1_data = {
        'username': username,
        'barcode_number': barcode_number,
        'order_number': order_number,
        'stage': 1,
        'start_time': start_time,
        'end_time': end_time,
        'created_at': datetime.utcnow(),
        'delay_status': delay_message
    }

    stage1_collection.insert_one(stage1_data)

    return jsonify({
        'message': 'Stage 1 recorded successfully!',
        'barcode_number': barcode_number,
        'order_number': order_number,
        'username': username,
        'stage': 1,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
        'delay_status': delay_message
    }), 201
@app.route('/stage2', methods=['POST'])
def stage2():
    data = request.get_json()
    barcode_number = data.get('barcode_number')
    user_token = request.headers.get('Authorization')

    if not barcode_number:
        return jsonify({'message': 'Barcode number is required!'}), 400

    if not user_token:
        return jsonify({'message': 'User token is required!'}), 401

    # Verify JWT token to get user data
    try:
        decoded_token = jwt.decode(user_token, app.config['SECRET_KEY'], algorithms=['HS256'])
        username = decoded_token['username']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token!'}), 401
    
    #  Check if a completed charge exists for this barcode number
    charge_data = stage1_collection.find_one({'barcode_number': barcode_number})
    
    if not charge_data:
        return jsonify({'message': 'Charge process for this barcode is not completed. Cannot proceed to Stage 1.'}), 400


    # Fetch the latest stage1 data for this barcode number
    stage1_data = stage1_collection.find_one({'barcode_number': barcode_number}, sort=[('created_at', -1)])

    if not stage1_data:
        return jsonify({'message': 'Stage1 data not found for this barcode!'}), 404

    stage1_end_time = stage1_data['end_time']
    current_time = datetime.utcnow()

    # Check if there is a delay beyond 45 minutes from stage1 end time
    if current_time > stage1_end_time:
        delay_time = current_time - stage1_end_time
        delay_message = f'Delayed by {delay_time.total_seconds() / 60:.2f} minutes'
    else:
        delay_message = 'On time'

    # Start a new 45-minute timer for stage2
    stage2_start_time = current_time
    stage2_end_time = stage2_start_time + timedelta(minutes=45)

    # Store this stage2 data in the stage2 collection
    stage2_data = {
        'username': username,
        'barcode_number': barcode_number,
        'order_number': stage1_data['order_number'],
        'stage': 2,
        'start_time': stage2_start_time,
        'end_time': stage2_end_time,
        'created_at': datetime.utcnow(),
        'delay_message': delay_message
    }

    # Insert the stage2 data into the collection
    stage2_collection.insert_one(stage2_data)

    # Return the response including new stage2 timing and delay message
    return jsonify({
        'message': 'Stage2 submitted successfully!',
        'barcode_number': barcode_number,
        'order_number': stage1_data['order_number'],
        'delay_message': delay_message,
        'stage2_start_time': stage2_start_time.isoformat(),
        'stage2_end_time': stage2_end_time.isoformat()
    }), 201

@app.route('/stage3', methods=['POST'])
def stage3():
    data = request.get_json()
    barcode_number = data.get('barcode_number')
    user_token = request.headers.get('Authorization')

    if not barcode_number:
        return jsonify({'message': 'Barcode number is required!'}), 400

    if not user_token:
        return jsonify({'message': 'User token is required!'}), 401

    # Verify JWT token to get user data
    try:
        decoded_token = jwt.decode(user_token, app.config['SECRET_KEY'], algorithms=['HS256'])
        username = decoded_token['username']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token!'}), 401

    # Check if stage2 was completed for this barcode number
    stage2_data = stage2_collection.find_one({'barcode_number': barcode_number}, sort=[('created_at', -1)])

    if not stage2_data:
        return jsonify({'message': 'Stage2 data not found for this barcode!'}), 404

    # Check if there is a delay beyond the stage2 end time
    stage2_end_time = stage2_data['end_time']
    current_time = datetime.utcnow()

    if current_time > stage2_end_time:
        delay_time = current_time - stage2_end_time
        delay_message = f'Delayed by {delay_time.total_seconds() / 60:.2f} minutes'
    else:
        delay_message = 'On time'

    # Start a new 45-minute timer for stage3
    stage3_start_time = current_time
    stage3_end_time = stage3_start_time + timedelta(minutes=5)

    # Store this stage3 data in the stage3 collection
    stage3_data = {
        'username': username,
        'barcode_number': barcode_number,
        'order_number': stage2_data['order_number'],
        'stage': 3,
        'start_time': stage3_start_time,
        'end_time': stage3_end_time,
        'created_at': datetime.utcnow(),
        'delay_message': delay_message
    }

    # Insert the stage3 data into the collection
    stage3_collection.insert_one(stage3_data)

    # Return the response including new stage3 timing and delay message
    return jsonify({
        'message': 'Stage3 submitted successfully!',
        'barcode_number': barcode_number,
        'order_number': stage2_data['order_number'],
        'delay_message': delay_message,
        'stage3_start_time': stage3_start_time.isoformat(),
        'stage3_end_time': stage3_end_time.isoformat()
    }), 201

@app.route('/stage4', methods=['POST'])
def stage4():
    data = request.get_json()
    barcode_number = data.get('barcode_number')
    user_token = request.headers.get('Authorization')

    if not barcode_number:
        return jsonify({'message': 'Barcode number is required!'}), 400

    if not user_token:
        return jsonify({'message': 'User token is required!'}), 401

    # Verify JWT token to get user data
    try:
        decoded_token = jwt.decode(user_token, app.config['SECRET_KEY'], algorithms=['HS256'])
        username = decoded_token['username']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token!'}), 401

    # Check if stage3 was completed for this barcode number
    stage3_data = stage3_collection.find_one({'barcode_number': barcode_number}, sort=[('created_at', -1)])

    if not stage3_data:
        return jsonify({'message': 'Stage3 data not found for this barcode!'}), 404

    # Check for delay beyond stage3 end time
    stage3_end_time = stage3_data['end_time']
    current_time = datetime.utcnow()

    if current_time > stage3_end_time:
        delay_time = current_time - stage3_end_time
        delay_message = f'Delayed by {delay_time.total_seconds() / 60:.2f} minutes'
    else:
        delay_message = 'On time'

    # Start a new 45-minute timer for stage4
    stage4_start_time = current_time
    stage4_end_time = stage4_start_time + timedelta(minutes=45)

    # Store this stage4 data in the stage4 collection
    stage4_data = {
        'username': username,
        'barcode_number': barcode_number,
        'order_number': stage3_data['order_number'],
        'stage': 4,
        'start_time': stage4_start_time,
        'end_time': stage4_end_time,
        'created_at': datetime.utcnow(),
        'delay_message': delay_message
    }

    # Insert the stage4 data into the collection
    stage4_collection.insert_one(stage4_data)

    return jsonify({
        'message': 'Stage4 submitted successfully!',
        'barcode_number': barcode_number,
        'order_number': stage3_data['order_number'],
        'delay_message': delay_message,
        'stage4_start_time': stage4_start_time.isoformat(),
        'stage4_end_time': stage4_end_time.isoformat()
    }), 201

@app.route('/stage5', methods=['POST'])
def stage5():
    data = request.get_json()
    barcode_number = data.get('barcode_number')
    user_token = request.headers.get('Authorization')

    if not barcode_number:
        return jsonify({'message': 'Barcode number is required!'}), 400

    if not user_token:
        return jsonify({'message': 'User token is required!'}), 401

    # Verify JWT token to get user data
    try:
        decoded_token = jwt.decode(user_token, app.config['SECRET_KEY'], algorithms=['HS256'])
        username = decoded_token['username']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token!'}), 401

    # Check if stage4 was completed for this barcode number
    stage4_data = stage4_collection.find_one({'barcode_number': barcode_number}, sort=[('created_at', -1)])

    if not stage4_data:
        return jsonify({'message': 'Stage4 data not found for this barcode!'}), 404

    # Check for delay beyond stage4 end time
    stage4_end_time = stage4_data['end_time']
    current_time = datetime.utcnow()

    if current_time > stage4_end_time:
        delay_time = current_time - stage4_end_time
        delay_message = f'Delayed by {delay_time.total_seconds() / 60:.2f} minutes'
    else:
        delay_message = 'On time'

    # Start a new 45-minute timer for stage5
    stage5_start_time = current_time
    stage5_end_time = stage5_start_time + timedelta(minutes=45)

    # Store this stage5 data in the stage5 collection
    stage5_data = {
        'username': username,
        'barcode_number': barcode_number,
        'order_number': stage4_data['order_number'],
        'stage': 5,
        'start_time': stage5_start_time,
        'end_time': stage5_end_time,
        'created_at': datetime.utcnow(),
        'delay_message': delay_message
    }

    # Insert the stage5 data into the collection
    stage5_collection.insert_one(stage5_data)

    return jsonify({
        'message': 'Stage5 submitted successfully!',
        'barcode_number': barcode_number,
        'order_number': stage4_data['order_number'],
        'delay_message': delay_message,
        'stage5_start_time': stage5_start_time.isoformat(),
        'stage5_end_time': stage5_end_time.isoformat()
    }), 201
@app.route('/report', methods=['GET'])
def report():
    # Get the order number from the request (change the parameter to 'order_number')
    order_no = request.args.get('order_number')

    if not order_no:
        return jsonify({"error": "Order number is required"}), 400

    # Query to find the order details
    order = orders_collection.find_one({"order_no": order_no})
    
    if not order:
        return jsonify({"error": "Order not found"}), 404

    # Get sizes and quantities from the order
    sizes_quantities = order.get('sizes_quantities', [])

    if not sizes_quantities:
        return jsonify({"error": "No sizes and quantities found for the order"}), 404
    
    # Prepare the report data
    report_data = []

    for size_qty in sizes_quantities:
        size = size_qty.get('size')
        quantity = size_qty.get('quantity')

        if not size or not quantity:
            continue

        # Check charged data
        charged_count = 0
        for barcode in size_qty.get('barcodes', []):
            # Check if barcode exists in both charged and stage_1 collections
            if charges_collection.find_one({"barcode": barcode}) and stage1_collection.find_one({"barcode": barcode}):
                charged_count += 1

        # Calculate balance
        balance = quantity - charged_count

        # Add details to report data
        report_data.append({
            'size': size,
            'quantity': quantity,
            'charged_count': charged_count,
            'balance': balance
        })
    
    if not report_data:
        return jsonify({"message": "No report data found for this order"}), 404
    
    return jsonify({"order_no": order_no, "report": report_data})


if __name__ == '__main__':
    app.run(debug=True)


