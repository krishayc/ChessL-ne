import os
import re
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


PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


def _rooks_connected(board, color):
    back_rank = 0 if color == chess.WHITE else 7
    rook = chess.Piece(chess.ROOK, color)
    rook_squares = [chess.square(f, back_rank) for f in range(8)
                     if board.piece_at(chess.square(f, back_rank)) == rook]
    if len(rook_squares) != 2:
        return False
    lo, hi = sorted(chess.square_file(s) for s in rook_squares)
    return not any(board.piece_at(chess.square(f, back_rank)) for f in range(lo + 1, hi))


def _semi_open_for_rook(board, color, file_idx):
    rook = chess.Piece(chess.ROOK, color)
    pawn = chess.Piece(chess.PAWN, color)
    squares = [chess.square(file_idx, r) for r in range(8)]
    if not any(board.piece_at(s) == rook for s in squares):
        return False
    return not any(board.piece_at(s) == pawn for s in squares)


def _new_coverage(board, move):
    before_attacks = board.attacks(move.from_square)
    board.push(move)
    after_attacks = board.attacks(move.to_square)
    board.pop()
    return after_attacks - before_attacks


def _newly_attacked_pieces(board, move, color, new_squares):
    targets = []
    for sq in new_squares:
        target = board.piece_at(sq)
        if target and target.color != color:
            targets.append((PIECE_NAMES[target.piece_type], chess.square_name(sq)))
    return targets


def _newly_defended_pieces(board, move, color, new_squares):
    defended = []
    for sq in new_squares:
        target = board.piece_at(sq)
        if target and target.color == color and sq != move.to_square:
            defended.append((PIECE_NAMES[target.piece_type], chess.square_name(sq)))
    return defended


CENTER_SQUARES = {chess.D4, chess.D5, chess.E4, chess.E5}


def _newly_controls_center(new_squares):
    return sorted(chess.square_name(sq) for sq in new_squares & CENTER_SQUARES)


def _mobility(board, move):
    before = len(board.attacks(move.from_square))
    board.push(move)
    after = len(board.attacks(move.to_square))
    board.pop()
    return before, after


def describe_move(board, move):
    mover = board.piece_at(move.from_square)
    color = mover.color
    from_file = chess.square_file(move.from_square)
    is_castle = board.is_castling(move)

    connected_before = _rooks_connected(board, color)
    open_before = _semi_open_for_rook(board, color, from_file)

    if is_castle:
        side = "kingside" if chess.square_file(move.to_square) == 6 else "queenside"
        who = "White" if color == chess.WHITE else "Black"
        desc = f"{who} castles {side}"
    else:
        mover_name = PIECE_NAMES[mover.piece_type]
        who = "White" if color == chess.WHITE else "Black"
        from_sq = chess.square_name(move.from_square)
        to_sq = chess.square_name(move.to_square)

        if board.is_en_passant(move):
            captured_name = "pawn"
        else:
            captured = board.piece_at(move.to_square)
            captured_name = PIECE_NAMES[captured.piece_type] if captured else None

        desc = f"{who}'s {mover_name} moves from {from_sq} to {to_sq}"
        if captured_name:
            desc += f", capturing the {captured_name}"
        if move.promotion:
            desc += f", promoting to a {PIECE_NAMES[move.promotion]}"

    board.push(move)
    gives_check = board.is_check()
    connected_after = _rooks_connected(board, color)
    open_after = _semi_open_for_rook(board, color, from_file)
    board.pop()

    connects_rooks = connected_after and not connected_before
    opens_file = open_after and not open_before and not is_castle

    if gives_check:
        desc += ", giving check"
    if connects_rooks:
        desc += ", connecting the rooks"
    if opens_file:
        desc += f", opening the {chess.FILE_NAMES[from_file]}-file for the rook"

    has_capture = bool(re.search(r"capturing the", desc))
    has_promotion = bool(move.promotion)
    extra_squares = []
    if not (has_capture or has_promotion or gives_check or connects_rooks or opens_file or is_castle):
        new_squares = _new_coverage(board, move)
        targets = _newly_attacked_pieces(board, move, color, new_squares)
        defends = _newly_defended_pieces(board, move, color, new_squares)
        center = _newly_controls_center(new_squares)

        if targets:
            piece_word, sq = targets[0]
            desc += f", newly attacking the {piece_word} on {sq}"
            extra_squares.append(sq)
        elif defends:
            piece_word, sq = defends[0]
            desc += f", newly defending the {piece_word} on {sq}"
            extra_squares.append(sq)
        elif center:
            squares_str = " and ".join(center)
            desc += f", newly controlling the center square{'s' if len(center) > 1 else ''} {squares_str}"
            extra_squares.extend(center)
        else:
            _, after = _mobility(board, move)
            desc += f", giving the {PIECE_NAMES[mover.piece_type]} control of {after} square{'s' if after != 1 else ''} from its new post"

    return desc + ".", extra_squares


def validate_explanation(explanation, move, extra_squares):
    """Reject the LLM's text if it references any square other than the
    move's own from/to squares plus whatever extra squares describe_move()
    actually computed (newly-attacked piece / newly-controlled center
    square). This is what guarantees no hallucinated squares make it to
    the user -- the prompt wording alone isn't reliable enough on its own.
    """
    mentioned_squares = set(re.findall(r"\b[a-h][1-8]\b", explanation.lower()))
    allowed_squares = {chess.square_name(move.from_square), chess.square_name(move.to_square)}
    allowed_squares.update(extra_squares)
    return mentioned_squares.issubset(allowed_squares)


def get_ai_explanation(board, move, san_move):
    fact, extra_squares = describe_move(board, move)
    mover_color = "White" if board.piece_at(move.from_square).color == chess.WHITE else "Black"
    prompt = (
        f"Chess move by {mover_color}. Established fact: {fact} "
        "In one confident sentence, written the way a chess commentator would "
        "describe this move, restate what's happening. Do not hedge with phrases "
        "like 'this move makes sense because', 'is simply a quiet developing "
        "move', or similar filler -- just state the fact plainly and directly, "
        "as if you're confidently narrating the position. Do not mention any "
        "square, file, piece, or plan that isn't part of the fact above. Do "
        f"not attribute this move to the wrong side -- it is {mover_color}'s move."
    )
    try:
        response = bedrock.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
        )
        # With reasoning enabled, content includes a reasoningContent block
        # *and* a text block — find the text one rather than assuming index 0.
        explanation = None
        for block in response["output"]["message"]["content"]:
            if "text" in block:
                explanation = block["text"].strip()
                break

        if explanation is None:
            return fact

        # Deterministic backstop: if the model mentioned a square that isn't
        # actually part of this move's true facts (the failure mode that
        # produced the e5/diagonal/pawn-structure nonsense), don't show it --
        # fall back to the ground-truth fact instead.
        if not validate_explanation(explanation, move, extra_squares):
            print(f"Rejected hallucinated explanation: {explanation!r}")
            return fact

        return explanation
    except Exception as e:
        print(f"Bedrock API error: {e}")
        return fact


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
    import time
    t0 = time.time()

    data = request.get_json()
    fen = data.get("fen")
    board = chess.Board(fen)

    best_move, eval_str = get_best_move(board)
    t1 = time.time()

    try:
        san_move = board.san(best_move) if best_move else "—"
    except Exception:
        san_move = str(best_move)

    explanation = (
        get_ai_explanation(board, best_move, san_move) if best_move else "No analysis available."
    )
    t2 = time.time()

    print(f"[timing] stockfish={t1 - t0:.2f}s  bedrock={t2 - t1:.2f}s  total={t2 - t0:.2f}s")

    return jsonify({
        "best_move": str(best_move) if best_move else "",
        "san_move": san_move,
        "evaluation": eval_str,
        "explanation": explanation,
        "turn": "white" if board.turn == chess.WHITE else "black"
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001, use_reloader=False)