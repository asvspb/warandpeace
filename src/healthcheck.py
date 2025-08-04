from flask import Flask, jsonify
import logging

# Отключаем стандартные логи Flask, чтобы не дублировать вывод
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    """
    Простая проверка работоспособности.
    Возвращает статус 200 OK, если приложение работает.
    """
    return jsonify(status="ok"), 200

def run_health_check_server():
    """
    Запускает Flask-сервер для health check в отдельном потоке.
    """
    # Запускаем на порту 8080, который будет доступен внутри Docker-сети
    app.run(host='0.0.0.0', port=8080, debug=False)

if __name__ == '__main__':
    print("Сервер для health check запущен на http://0.0.0.0:8080/health")
    run_health_check_server()
