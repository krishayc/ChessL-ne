import chess
import chess.engine

engine = chess.engine.SimpleEngine.popen_uci("./stockfish")

board = chess.Board()

result = engine.play(board, chess.engine.Limit(time=1.0))

print("Best move:", result.move)

engine.quit()