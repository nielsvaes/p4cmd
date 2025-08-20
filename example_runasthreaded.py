"""
Example demonstrating the RunAsThreaded context manager for syncing folders
"""

import time
from p4cmd import P4Client, RunAsThreaded, P4Operation

def on_operation_started(operation):
    """Called when an operation starts"""
    print(f"🚀 Started: {operation.method_name}")
    
    # Show which folders are being synced
    if operation.method_name == 'sync_folders':
        folders = operation.get_argument(0)
        if folders:
            print(f"   Syncing: {folders}")

def on_operation_completed(operation):
    """Called when an operation completes"""
    duration = operation.duration()
    print(f"✅ Completed: {operation.method_name} in {duration:.2f}s")
    
    if operation.method_name == 'sync_folders':
        folders = operation.get_argument(0)
        print(f"   Successfully synced: {folders}")

def on_operation_failed(operation):
    """Called when an operation fails"""
    print(f"❌ Failed: {operation.method_name} - {operation.error}")

def main():
    # Initialize P4Client (adjust path to your workspace)
    p4_client = P4Client(r"D:\p4\games")
    
    # Connect to signals to monitor progress
    p4_client.connect_signal(P4Operation.STARTED, on_operation_started)
    p4_client.connect_signal(P4Operation.COMPLETED, on_operation_completed)
    p4_client.connect_signal(P4Operation.FAILED, on_operation_failed)
    
    print("=== Synchronous sync (blocking) ===")
    start_time = time.time()
    
    # This will run synchronously and block
    result1 = p4_client.sync_folders(["//games/main/Raw/Discovery/Content/Discovery/Animations/AnimationDatabase/Cinematics/AlphaTrailer/"])
    print(f"Sync 1 finished. Type: {type(result1)}")
    
    result2 = p4_client.sync_folders(["//games/main/Raw/Discovery/Content/Discovery/Animations/AnimationDatabase/Cinematics/BetaTeaser/"])
    print(f"Sync 2 finished. Type: {type(result2)}")
    
    sync_time = time.time() - start_time
    print(f"Total synchronous time: {sync_time:.2f}s\n")
    
    print("=== Asynchronous sync with RunAsThreaded ===")
    start_time = time.time()
    
    # Use RunAsThreaded context manager for threaded execution
    with RunAsThreaded(p4_client):
        # These will run asynchronously and return operation IDs
        op1_id = p4_client.sync_folders(["//games/main/Raw/Discovery/Content/Discovery/Animations/AnimationDatabase/Cinematics/LaunchTrailer/"])
        op2_id = p4_client.sync_folders(["//games/main/Raw/Discovery/Content/Discovery/Animations/AnimationDatabase/Cinematics/OpenBeta/"])
        
        print(f"Queued sync operations: {op1_id}, {op2_id}")
        print("Operations are running in background...")
        
        # You can do other work here while syncing happens
        print("Doing other work while syncing...")
        time.sleep(0.5)
        
        # Check status of operations
        op1_status = p4_client.get_operation_status(op1_id)
        op2_status = p4_client.get_operation_status(op2_id)
        
        print(f"Operation 1 status: {op1_status.status.value}")
        print(f"Operation 2 status: {op2_status.status.value}")
        
        # Wait for specific operations to complete
        print("Waiting for operations to complete...")
        result1 = p4_client.wait_for_operation(op1_id, timeout=30.0)
        result2 = p4_client.wait_for_operation(op2_id, timeout=30.0)
        
        print(f"Operation 1 result: {type(result1) if result1 else 'None/Timeout'}")
        print(f"Operation 2 result: {type(result2) if result2 else 'None/Timeout'}")
    
    # Outside the context manager, operations return to synchronous mode
    print("\n=== Back to synchronous mode ===")
    result3 = p4_client.sync_folders(["//games/main/Raw/Discovery/Content/Discovery/Animations/AnimationDatabase/Cinematics/Season3Trailer/"])
    print(f"Sync 3 finished. Type: {type(result3)}")
    
    async_time = time.time() - start_time
    print(f"Total asynchronous time: {async_time:.2f}s")
    
    # Show all operations that were executed
    print(f"\n=== Operation Summary ===")
    all_ops = p4_client.get_all_operations()
    for op_id, operation in all_ops.items():
        status_emoji = {
            "completed": "✅",
            "failed": "❌", 
            "cancelled": "🚫",
            "running": "⏳",
            "pending": "⏸️"
        }.get(operation.status.value, "❓")
        
        duration_str = f" ({operation.duration():.2f}s)" if operation.duration() else ""
        folders = operation.get_argument(0) if operation.method_name == 'sync_folders' else []
        
        print(f"  {status_emoji} {op_id}: {operation.method_name}{duration_str}")
        print(f"     Folders: {folders}")
    
    # Clean shutdown
    p4_client.shutdown_threading()
    print("\nExample completed!")

if __name__ == "__main__":
    main()
