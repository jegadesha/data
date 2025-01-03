from flask import jsonify

class AuthService:
    def __init__(self):
        pass
    def login(self):
        pass
    def register(self, request):
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