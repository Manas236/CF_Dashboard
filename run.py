from app import config, create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=config.DASH_HOST, port=config.DASH_PORT, debug=config.FLASK_DEBUG)
