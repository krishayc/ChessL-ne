import os
import atexit
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
import chess
import chess.engine
import boto3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.amazon.nova-2-lite-v1:0")

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=AWS_REGION,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)

engine = chess.engine.SimpleEngine.popen_uci("./stockfish")
engine_lock = threading.Lock() 


@atexit.register
def shutdown_engine():
    """Make sure Stockfish is closed cleanly when Flask shuts down."""
    try:
        engine.quit()
    except Exception:
        pass


def get_ai_explanation(fen, san_move):
    prompt = (
        f"You are a master chess analyst. Given the board position in FEN format: '{fen}', "
        f"Stockfish recommends playing the move '{san_move}'. "
        f"In exactly 1 concise sentence, explain the tactical or strategic reason for this move "
        f"using standard chess terms (like capturing a piece, controlling an open file, creating a threat). "
        f"Do not include meta-commentary or mention FEN strings."
    )
    try:
        response = bedrock.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
        )
        return response["output"]["message"]["content"][0]["text"].strip()
    except Exception as e:
        print(f"Bedrock API error: {e}")
        return "Could not fetch AI explanation right now."


def get_best_move(board):
    try:
        with engine_lock:
            info = engine.analyse(board, chess.engine.Limit(time=0.3))

        best_move = info["pv"][0] if "pv" in info and info["pv"] else None

        eval_str = "0.00"
        if "score" in info:
            score = info["score"].relative
            if score.is_mate():
                eval_str = f"M{score.mate()}"
            else:
                cp = score.score()
                eval_str = f"{cp / 100:+.2f}" if cp is not None else "0.00"

        return best_move, eval_str

    except Exception as e:
        print(f"Stockfish error: {e}")
        legal = list(board.legal_moves)
        return (legal[0] if legal else None), "0.00"


@app.route("/analyse", methods=["POST"])
def analyse():
    data = request.get_json()
    fen = data.get("fen")
    board = chess.Board(fen)

    best_move, eval_str = get_best_move(board)

    try:
        san_move = board.san(best_move) if best_move else "—"
    except Exception:
        san_move = str(best_move)

    explanation = get_ai_explanation(fen, san_move) if best_move else "No analysis available."

    return jsonify({
        "best_move": str(best_move) if best_move else "",
        "san_move": san_move,
        "evaluation": eval_str,
        "explanation": explanation,
        "turn": "white" if board.turn == chess.WHITE else "black"
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001, use_reloader=False)