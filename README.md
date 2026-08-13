# ChessL!!ne

## Setup

This project requires the Stockfish chess engine binary, which is not
included in this repo (too large for GitHub).

1. Download Stockfish for your platform: https://stockfishchess.org/download/
2. Place the binary in the project root and rename it to `stockfish`
3. Make it executable:
   \`\`\`
   chmod +x stockfish
   \`\`\`
4. Install Python libraries:
   \`\`\`
   pip install -r requirements.txt
   \`\`\`
5. Create a `.env` file with your AWS credentials:
   \`\`\`
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_REGION=ap-south-1
   BEDROCK_MODEL_ID=global.amazon.nova-2-lite-v1:0
   \`\`\`
6. Run the backend:
   \`\`\`
   python3 main.py
   \`\`\`
7. Open `index.html` with a local server.