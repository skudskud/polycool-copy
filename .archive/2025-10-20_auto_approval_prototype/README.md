# Auto-Approval Prototype

## 🔬 Event-Driven Wallet Funding Detection Test

This prototype tests real-time detection of wallet funding and automatic approval + API generation on Polygon mainnet.

### 🚀 Quick Start

1. **Install dependencies:**
   ```bash
   cd auto-approval-prototype
   pip install -r requirements.txt
   ```

2. **Run the prototype:**
   ```bash
   python prototype_main.py
   ```

3. **Follow the funding instructions** displayed in the terminal

4. **Watch the magic happen!** Auto-approval will trigger automatically when funding is detected

### 📁 Files Structure

- `prototype_main.py` - Main entry point
- `wallet_generator.py` - Generates test wallets  
- `event_listener.py` - Real-time funding detection
- `auto_approval_engine.py` - Orchestrates approval + API generation
- `config.py` - Configuration settings
- `shared_modules/` - Production code modules
- `test_results/` - Test results and logs

### 🎯 What This Tests

1. **Wallet Generation** - Creates fresh test wallet
2. **Event Monitoring** - Real-time balance monitoring (every 2 seconds)
3. **Funding Detection** - Detects USDC.e + POL funding
4. **Auto-Approval** - Automatically approves Polymarket contracts
5. **API Generation** - Generates working API credentials
6. **Performance Measurement** - Times every step

### 📊 Success Criteria

- ✅ Event detection < 15 seconds after funding
- ✅ Auto-approval completes successfully
- ✅ API credentials generated and tested
- ✅ Total time < 90 seconds from funding to ready

### 🔧 Configuration

Edit `config.py` to adjust:
- Monitoring intervals
- Balance requirements
- RPC endpoints
- Logging levels

### 🧪 Test Results

Results are automatically saved to `test_results/latest_test.json` with detailed timing and success metrics.
