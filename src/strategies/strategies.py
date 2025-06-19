import asyncio
import os
from typing import Dict, List, Any, Optional
from web3 import Web3, AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.providers.rpc import AsyncHTTPProvider
from eth_account import Account
from config import logger
from strategies.strategy_config import STRATEGY_CONTRACTS, STRATEGY_FUNCTIONS


# Contract ABIs - minimal required for strategy execution
VAULT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "targetContract", "type": "address"},
            {"internalType": "bytes", "name": "data", "type": "bytes"},
            {"components": [
                {"internalType": "address", "name": "token", "type": "address"},
                {"internalType": "uint256", "name": "amount", "type": "uint256"}
            ], "internalType": "struct IVault.TokenApproval[]", "name": "approvals", "type": "tuple[]"}
        ],
        "name": "executeStrategy",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

class StrategyExecutor:
    def __init__(self, rpc_url: str, private_key: str):
        """
        Initialize the strategy executor
        
        Args:
            rpc_url: RPC endpoint URL
            private_key: Private key of the authorized manager
        """
        self.w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        # Note: AsyncWeb3 doesn't use middleware the same way, check if POA middleware is needed
        
        self.account = Account.from_key(private_key)
        
        logger.info(f"Initialized async strategy executor with account: {self.account.address}")

    async def execute_strategy(
        self,
        vault_address: str,
        target_contract: str,
        call_data: bytes,
        approvals: List[tuple],
        gas_limit: Optional[int] = None
    ) -> str:
        """
        Generic strategy execution function
        
        Args:
            vault_address: Address of the vault contract
            target_contract: Address of the target contract to call
            call_data: Encoded function call data
            approvals: List of token approvals needed
            gas_limit: Optional gas limit override
            
        Returns:
            Transaction hash
        """
        try:
            # Get vault contract
            vault_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(vault_address),
                abi=VAULT_ABI
            )
            
            # Get nonce and gas price asynchronously
            nonce = await self.w3.eth.get_transaction_count(self.account.address)
            gas_price = await self.w3.eth.gas_price
            
            # Build transaction
            transaction = await vault_contract.functions.executeStrategy(
                Web3.to_checksum_address(target_contract),
                call_data,
                approvals
            ).build_transaction({
                'from': self.account.address,
                'nonce': nonce,
                'gas': gas_limit or 500000,
                'gasPrice': gas_price,
            })
            
            # Sign and send transaction
            signed_txn = self.w3.eth.account.sign_transaction(transaction, self.account.key)
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            
            logger.info(f"Strategy executed. TX hash: {tx_hash.hex()}")
            return tx_hash.hex()
            
        except Exception as e:
            logger.error(f"Error executing strategy: {str(e)}")
            raise








