# Strategy Execution Flow Testing

This document explains how strategies work in the DeMether system and how to test them manually.

## Strategy Execution Flow

### 1. **Strategy Definition** (`src/services/strategies.py`)
- Strategies are defined with metadata (name, description, tokens, chains)
- Each strategy has a `task` template with placeholders (e.g., `{percentage}`)

### 2. **User Subscription** (via API endpoints)
- Users subscribe to strategies via `/strategies/subscribe` endpoint
- Creates a task in MongoDB with user-specific parameters
- Task gets scheduled based on strategy frequency (daily, hourly, etc.)

### 3. **Task Scheduling** (`src/services/task_manager.py`)
- Tasks are stored in MongoDB with `next_run_time` field
- New tasks are scheduled to run in 5 minutes for immediate testing
- Subsequent runs follow the strategy frequency (daily = +24 hours)

### 4. **Task Execution** (`src/services/task_executor.py`)
- `/tasks` endpoint can be called to execute the next due task
- TaskExecutor formats the strategy task with user parameters
- Uses StrategyExecutor to run the AI-powered execution
- Marks task as completed and schedules next run
- Sends Telegram notifications if configured

### 5. **Strategy Execution** (`src/services/strategy_execution.py`)
- AI agent analyzes the task and portfolio data
- Compares yields across ALL protocols (Aave, Colend, Morpho)
- Executes swaps and deposits to achieve highest yields
- Returns structured report with transactions and memo

## Manual Testing

### Prerequisites
```bash
cd /Users/jdorado/dev/demether/demai-api
poetry shell
```

### 1. List Available Strategies
```bash
python src/test_strategy_flow.py --list-strategies
```

### 2. Test Direct Strategy Execution (No Task Creation)
```bash
python src/test_strategy_flow.py \
  --strategy katana_ausd_morpho_optimizer \
  --vault 0x1234567890123456789012345678901234567890 \
  --user 0x1234567890123456789012345678901234567890 \
  --percentage 25 \
  --direct-only
```

### 3. Test Full Task Workflow (Create → Execute → Cleanup)
```bash
python src/test_strategy_flow.py \
  --strategy katana_ausd_morpho_optimizer \
  --vault 0x1234567890123456789012345678901234567890 \
  --user 0x1234567890123456789012345678901234567890 \
  --percentage 25
```

### 4. Check What Tasks Are Due
```bash
python src/test_strategy_flow.py --check-due
```

### 5. Clean Up Test Tasks
```bash
python src/test_strategy_flow.py \
  --user 0x1234567890123456789012345678901234567890 \
  --cleanup
```

## Production Task Execution

### Via API Endpoint
```bash
curl -X GET "http://localhost:8000/tasks"
```
This endpoint:
- Gets the next due task from the database
- Executes it using the AI agent
- Updates the task with results and next run time
- Sends notifications if configured

### Via Cron Job
Set up a cron job to call the `/tasks` endpoint regularly:
```bash
# Execute due tasks every 5 minutes
*/5 * * * * curl -X GET "http://localhost:8000/tasks" > /dev/null 2>&1
```

## Strategy Examples

### Core Stablecoin Optimizer
- **Task**: "Analyze yields for USDT and USDC on Core chain, swap 25% of Core funds to the higher yielding stablecoin, and deposit into the best lending protocol"
- **Execution**: 
  1. Check portfolio for USDT/USDC balances on Core
  2. Compare Aave/Colend yields for both tokens
  3. Swap to higher yielding token if needed
  4. Deposit to best protocol

### Katana AUSD Morpho Optimizer  
- **Task**: "Compare yields between Steakhouse Prime AUSD Vault (0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD) and Gauntlet AUSD Vault (0x9540441C503D763094921dbE4f13268E6d1d3B56) on Katana, then move 25% of AUSD funds to the highest yielding MetaMorpho vault"
- **Execution**:
  1. Check portfolio for AUSD balance on Katana
  2. Compare yields between Steakhouse Prime (3.87%) and Gauntlet (3.24%) vaults
  3. Move funds to Steakhouse Prime (higher yield)
  4. Execute via morpho_lending tool

## Expected Results

### Successful Execution
```json
{
  "status": "success",
  "task": "Compare yields between...",
  "actions_taken": [
    "view_portfolio: {...}",
    "morpho_lending: {chain_name: 'Katana', token_symbol: 'AUSD', amount: 125.0, action: 'supply', market_id: '0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD'}"
  ],
  "transactions": [
    "https://katana-explorer.vercel.app/tx/0x..."
  ],
  "result": "Successfully deposited 125 AUSD to Steakhouse Prime vault",
  "memo": "Moved 25% AUSD (125 tokens) to Steakhouse Prime vault for 3.87% APY"
}
```

### Task Execution Flow
1. **Task Retrieved**: Next due task from MongoDB
2. **Strategy Formatted**: "Compare yields... move 25% of AUSD funds..."
3. **AI Execution**: Agent analyzes portfolio and yields
4. **Tools Used**: view_portfolio → morpho_lending  
5. **Result**: Transaction executed, task marked complete
6. **Next Schedule**: +24 hours for daily strategy

## Troubleshooting

### Common Issues
1. **"No tasks due for execution"**: No tasks are scheduled or none are due yet
2. **"Strategy not found"**: Invalid strategy_id in task
3. **"Insufficient balance"**: Portfolio doesn't have enough tokens
4. **"Web3 connections not ready"**: RPC endpoints not accessible

### Debug Steps
1. Check task exists: Look in MongoDB `strategy_tasks` collection
2. Verify task timing: Check `next_run_time` field
3. Test yields: Run `python src/test_morpho_yields.py` 
4. Test portfolio: Check vault has funds before executing
5. Check logs: Review execution logs for detailed errors

## Database Schema

### Strategy Tasks Collection
```javascript
{
  "_id": ObjectId,
  "user_address": "0x...",      // User's wallet
  "vault_address": "0x...",     // User's vault  
  "strategy_id": "katana_ausd_morpho_optimizer",
  "chain": "katana",
  "percentage": 25,
  "enabled": true,
  "created_at": ISODate,
  "updated_at": ISODate,
  "last_executed": ISODate,
  "next_run_time": ISODate,     // When to run next
  "execution_count": 5,
  "last_execution_memo": "Moved 25% AUSD to Steakhouse Prime vault",
  "last_execution_status": "success"
}
```