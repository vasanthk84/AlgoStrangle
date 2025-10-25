"""
cache_manager.py
Utility script to manage backtest cache
"""

import os
from pathlib import Path
import pickle
from datetime import datetime
from colorama import Fore, Style
from tabulate import tabulate


def get_cache_info(cache_dir: str = "backtest_cache") -> dict:
    """Get information about cached data"""
    cache_path = Path(cache_dir)
    
    if not cache_path.exists():
        return {"exists": False}
    
    info = {
        "exists": True,
        "instruments": [],
        "nifty": [],
        "vix": [],
        "options": []
    }
    
    for subdir in ["instruments", "nifty", "vix", "options"]:
        subdir_path = cache_path / subdir
        if subdir_path.exists():
            for file in subdir_path.glob("*.pkl"):
                file_size = file.stat().st_size / (1024 * 1024)  # MB
                modified = datetime.fromtimestamp(file.stat().st_mtime)
                info[subdir].append({
                    "file": file.name,
                    "size_mb": file_size,
                    "modified": modified
                })
    
    return info


def display_cache_status(cache_dir: str = "backtest_cache"):
    """Display cache status"""
    print(f"\n{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}BACKTEST CACHE STATUS{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}\n")
    
    info = get_cache_info(cache_dir)
    
    if not info["exists"]:
        print(f"{Fore.YELLOW}Cache directory does not exist. No cached data.{Style.RESET_ALL}")
        return
    
    total_size = 0
    total_files = 0
    
    for data_type in ["instruments", "nifty", "vix", "options"]:
        files = info[data_type]
        if files:
            print(f"\n{Fore.GREEN}{data_type.upper()} Cache:{Style.RESET_ALL}")
            print(f"  Files: {len(files)}")
            
            data = []
            for file_info in sorted(files, key=lambda x: x['modified'], reverse=True)[:5]:
                data.append([
                    file_info['file'][:50],
                    f"{file_info['size_mb']:.2f} MB",
                    file_info['modified'].strftime("%Y-%m-%d %H:%M")
                ])
                total_size += file_info['size_mb']
                total_files += 1
            
            print(tabulate(data, headers=["File", "Size", "Modified"], tablefmt="simple"))
            
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more files")
        else:
            print(f"\n{Fore.YELLOW}{data_type.upper()} Cache: Empty{Style.RESET_ALL}")
    
    print(f"\n{Fore.CYAN}Summary:{Style.RESET_ALL}")
    print(f"  Total Files: {total_files}")
    print(f"  Total Size: {total_size:.2f} MB")
    print()


def clear_cache(cache_dir: str = "backtest_cache", data_type: str = None):
    """Clear cache files"""
    cache_path = Path(cache_dir)
    
    if not cache_path.exists():
        print(f"{Fore.YELLOW}No cache directory found.{Style.RESET_ALL}")
        return
    
    deleted_count = 0
    deleted_size = 0
    
    if data_type:
        # Clear specific type
        subdir_path = cache_path / data_type
        if subdir_path.exists():
            for file in subdir_path.glob("*.pkl"):
                size = file.stat().st_size / (1024 * 1024)
                file.unlink()
                deleted_count += 1
                deleted_size += size
            print(f"{Fore.GREEN}Cleared {deleted_count} files ({deleted_size:.2f} MB) from {data_type} cache{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}No {data_type} cache found{Style.RESET_ALL}")
    else:
        # Clear all cache
        for subdir in ["instruments", "nifty", "vix", "options"]:
            subdir_path = cache_path / subdir
            if subdir_path.exists():
                for file in subdir_path.glob("*.pkl"):
                    size = file.stat().st_size / (1024 * 1024)
                    file.unlink()
                    deleted_count += 1
                    deleted_size += size
        print(f"{Fore.GREEN}Cleared all cache: {deleted_count} files ({deleted_size:.2f} MB){Style.RESET_ALL}")


def inspect_cache_file(cache_dir: str, data_type: str, filename: str):
    """Inspect a specific cache file"""
    cache_path = Path(cache_dir) / data_type / filename
    
    if not cache_path.exists():
        print(f"{Fore.RED}File not found: {cache_path}{Style.RESET_ALL}")
        return
    
    try:
        with open(cache_path, 'rb') as f:
            data = pickle.load(f)
        
        print(f"\n{Fore.CYAN}Cache File: {filename}{Style.RESET_ALL}")
        print(f"Type: {type(data)}")
        
        if hasattr(data, '__len__'):
            print(f"Length: {len(data)}")
        
        if isinstance(data, list) and len(data) > 0:
            print(f"\nFirst item sample:")
            print(data[0])
        elif hasattr(data, 'head'):
            print(f"\nDataFrame info:")
            print(f"Shape: {data.shape}")
            print(f"Columns: {list(data.columns)}")
            print(f"\nFirst few rows:")
            print(data.head())
        
    except Exception as e:
        print(f"{Fore.RED}Error reading file: {e}{Style.RESET_ALL}")


def main():
    print(f"""
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
{Fore.CYAN}  BACKTEST CACHE MANAGER  {Style.RESET_ALL}
{Fore.CYAN}{'=' * 80}{Style.RESET_ALL}
""")
    
    print("\nSelect an option:")
    print("1. Show cache status")
    print("2. Clear all cache")
    print("3. Clear specific cache type")
    print("4. Inspect cache file")
    print("5. Exit")
    
    choice = input("\nEnter choice (1-5): ").strip()
    
    if choice == "1":
        display_cache_status()
    
    elif choice == "2":
        confirm = input(f"{Fore.YELLOW}Are you sure you want to clear ALL cache? (yes/no): {Style.RESET_ALL}").lower()
        if confirm == "yes":
            clear_cache()
        else:
            print(f"{Fore.YELLOW}Cancelled{Style.RESET_ALL}")
    
    elif choice == "3":
        print("\nSelect cache type to clear:")
        print("1. Instruments")
        print("2. NIFTY data")
        print("3. VIX data")
        print("4. Options data")
        
        type_choice = input("Enter choice (1-4): ").strip()
        type_map = {"1": "instruments", "2": "nifty", "3": "vix", "4": "options"}
        
        if type_choice in type_map:
            data_type = type_map[type_choice]
            confirm = input(f"{Fore.YELLOW}Clear {data_type} cache? (yes/no): {Style.RESET_ALL}").lower()
            if confirm == "yes":
                clear_cache(data_type=data_type)
            else:
                print(f"{Fore.YELLOW}Cancelled{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}Invalid choice{Style.RESET_ALL}")
    
    elif choice == "4":
        data_type = input("Enter cache type (instruments/nifty/vix/options): ").strip()
        filename = input("Enter filename: ").strip()
        inspect_cache_file("backtest_cache", data_type, filename)
    
    elif choice == "5":
        print(f"{Fore.GREEN}Goodbye!{Style.RESET_ALL}")
    
    else:
        print(f"{Fore.RED}Invalid choice{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
