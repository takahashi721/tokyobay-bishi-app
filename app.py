from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/")
def index():
    date = request.args.get("date")
    return render_template("index.html", date=date)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
