import requests
import json
from typing import Optional, Dict
import time

class PriceFetcher:
    """Fetches token prices from multiple sources including dextools.io, Jupiter (Solana), and others"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.dextools.io/"
        }
    
    def get_price(self, token_address: str, chain: str) -> Optional[float]:
        """
        Fetch token price from multiple sources
        
        Args:
            token_address: Token contract address
            chain: Chain name (evm, solana, sui)
        
        Returns:
            Token price as float or None if failed
        """
        try:
            chain = chain.lower()
            
            if chain == "solana":
                return self._fetch_solana_price(token_address)
            elif chain == "sui":
                return self._fetch_sui_price(token_address)
            else:  # EVM chains
                return self._fetch_evm_price(token_address, chain)
        except Exception as e:
            print(f"Error fetching price for {token_address} on {chain}: {e}")
            return None
    
    def _fetch_solana_price(self, address: str) -> Optional[float]:
        """Fetch Solana token price using multiple methods"""
        # Method 1: Try Jupiter API (Solana DEX aggregator)
        price = self._fetch_from_jupiter(address)
        if price is not None:
            return price
        
        # Method 2: Try DexScreener API (popular alternative)
        price = self._fetch_from_dexscreener(address, "solana")
        if price is not None:
            return price
        
        # Method 3: Try DexTools with different endpoints
        price = self._fetch_from_dextools(address, "solana")
        if price is not None:
            return price
        
        # Method 4: Try Birdeye API (Solana price aggregator)
        price = self._fetch_from_birdeye(address)
        if price is not None:
            return price
        
        return None
    
    def _fetch_from_jupiter(self, address: str) -> Optional[float]:
        """Fetch price from Jupiter API (Solana)"""
        try:
            # Jupiter price API
            url = f"https://price.jup.ag/v4/price?ids={address}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and address in data['data']:
                    token_data = data['data'][address]
                    if 'price' in token_data:
                        return float(token_data['price'])
        except requests.exceptions.SSLError:
            # SSL errors are common, just skip this method
            pass
        except Exception as e:
            # Only print non-SSL errors to avoid spam
            if "SSL" not in str(e):
                print(f"Jupiter API error: {e}")
        return None
    
    def _fetch_from_dexscreener(self, address: str, chain: str) -> Optional[float]:
        """Fetch price from DexScreener API"""
        try:
            chain_map = {
                "solana": "solana",
                "ethereum": "ethereum",
                "bsc": "bsc",
                "polygon": "polygon",
                "arbitrum": "arbitrum",
                "optimism": "optimism",
                "avalanche": "avalanche",
                "sui": "sui",
                "evm": "ethereum"
            }
            chain_id = chain_map.get(chain.lower(), chain.lower())
            
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'pairs' in data and len(data['pairs']) > 0:
                    # Get the pair with highest liquidity
                    pairs = sorted(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0), reverse=True)
                    if pairs:
                        pair = pairs[0]
                        if 'priceUsd' in pair:
                            return float(pair['priceUsd'])
                        elif 'priceNative' in pair:
                            # Try to get USD price from priceNative if available
                            return float(pair.get('priceUsd', 0))
        except Exception as e:
            print(f"DexScreener API error: {e}")
        return None
    
    def _fetch_from_birdeye(self, address: str) -> Optional[float]:
        """Fetch price from Birdeye API (Solana)"""
        try:
            # Birdeye public API endpoint
            url = f"https://public-api.birdeye.so/v1/token/price?address={address}"
            headers = {
                **self.headers,
                "X-API-KEY": ""  # Public endpoint might not need key
            }
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'value' in data['data']:
                    return float(data['data']['value'])
        except Exception as e:
            print(f"Birdeye API error: {e}")
        return None
    
    def _fetch_from_dextools(self, address: str, chain: str) -> Optional[float]:
        """Fetch price from DexTools using various methods"""
        try:
            # Try different DexTools endpoints
            endpoints = [
                f"https://www.dextools.io/shared/data/pair?address={address}&chain={chain}",
                f"https://api.dextools.io/v1/token/{chain}/{address}",
            ]
            
            for url in endpoints:
                try:
                    response = requests.get(url, headers=self.headers, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        price = self._extract_price_from_response(data)
                        if price is not None:
                            return price
                except:
                    continue
        except Exception as e:
            print(f"DexTools API error: {e}")
        return None
    
    def _fetch_evm_price(self, address: str, chain: str) -> Optional[float]:
        """Fetch EVM token price"""
        # Method 1: Try DexScreener (works for most EVM chains)
        price = self._fetch_from_dexscreener(address, chain)
        if price is not None:
            return price
        
        # Method 2: Try DexTools
        price = self._fetch_from_dextools(address, chain)
        if price is not None:
            return price
        
        return None
    
    def _fetch_sui_price(self, address: str) -> Optional[float]:
        """Fetch Sui token price"""
        # Method 1: Try DexScreener
        price = self._fetch_from_dexscreener(address, "sui")
        if price is not None:
            return price
        
        # Method 2: Try DexTools
        price = self._fetch_from_dextools(address, "sui")
        if price is not None:
            return price
        
        return None
    
    def _extract_price_from_response(self, data: dict) -> Optional[float]:
        """Extract price from various possible response structures"""
        try:
            # Try nested data.price
            if 'data' in data and isinstance(data['data'], dict):
                price_data = data['data']
                if 'price' in price_data:
                    return float(price_data['price'])
                if 'priceUSD' in price_data:
                    return float(price_data['priceUSD'])
                if 'priceUsd' in price_data:
                    return float(price_data['priceUsd'])
            
            # Try direct price fields
            if 'price' in data:
                return float(data['price'])
            if 'priceUSD' in data:
                return float(data['priceUSD'])
            if 'priceUsd' in data:
                return float(data['priceUsd'])
            
            # Try result.price
            if 'result' in data and isinstance(data['result'], dict):
                result = data['result']
                if 'price' in result:
                    return float(result['price'])
                if 'priceUSD' in result:
                    return float(result['priceUSD'])
            
            # Try pairs array (DexScreener format)
            if 'pairs' in data and isinstance(data['pairs'], list) and len(data['pairs']) > 0:
                pair = data['pairs'][0]
                if 'priceUsd' in pair:
                    return float(pair['priceUsd'])
                if 'price' in pair:
                    return float(pair['price'])
            
            return None
        except (ValueError, KeyError, TypeError) as e:
            print(f"Error extracting price: {e}")
            return None
