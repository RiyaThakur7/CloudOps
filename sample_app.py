
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "Sample Application is Running!"

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "application": "CloudOps Sample App"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
