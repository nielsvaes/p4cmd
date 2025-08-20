"""
Example usage of ThreadedP4Client with signal system
"""

import time
from p4cmd import ThreadedP4Client, OperationStatus, P4Operation

def on_operation_started(operation):
    """Called when an operation starts"""
    print(f"🚀 Operation {operation.operation_id} ({operation.method_name}) started")
    
    # Access specific operation information
    if operation.method_name == 'sync_folders':
        folders = operation.get_folders()
        if folders:
            print(f"   Syncing folders: {folders}")
    elif operation.method_name == 'sync_files':
        files = operation.get_files()
        revision = operation.get_keyword_argument('revision', -1)
        force = operation.get_keyword_argument('force', False)
        print(f"   Syncing {len(files)} files")
        print(f"   Revision: {'latest' if revision == -1 else revision}")
        print(f"   Force: {force}")
    elif operation.method_name == 'make_new_changelist':
        description = operation.get_argument(0, "No description")
        print(f"   Creating changelist: '{description}'")

def on_operation_progress(operation):
    """Called during operation progress updates"""
    print(f"⏳ Operation {operation.operation_id}: {operation.progress:.1f}% complete")

def on_operation_completed(operation):
    """Called when an operation completes successfully"""
    duration = operation.duration()
    print(f"✅ Operation {operation.operation_id} completed in {duration:.2f}s")
    
    # Show operation-specific completion info
    if operation.method_name == 'sync_folders':
        folders = operation.get_folders()
        print(f"   Successfully synced folders: {folders}")
    elif operation.method_name == 'sync_files':
        files = operation.get_files()
        print(f"   Successfully synced {len(files)} files")

def on_operation_failed(operation):
    """Called when an operation fails"""
    print(f"❌ Operation {operation.operation_id} failed: {operation.error}")
    
    # Show what was being processed when it failed
    if operation.method_name == 'sync_folders':
        folders = operation.get_folders()
        print(f"   Failed while syncing: {folders}")

def on_operation_cancelled(operation):
    """Called when an operation is cancelled"""
    print(f"🚫 Operation {operation.operation_id} was cancelled")

def main():
    # Create a ThreadedP4Client
    p4_client = ThreadedP4Client("D:/your/perforce/workspace")
    
    # Connect to signals using the new class properties for autocomplete
    p4_client.connect_signal(P4Operation.STARTED, on_operation_started)
    p4_client.connect_signal(P4Operation.PROGRESS, on_operation_progress)
    p4_client.connect_signal(P4Operation.COMPLETED, on_operation_completed)
    p4_client.connect_signal(P4Operation.FAILED, on_operation_failed)
    p4_client.connect_signal(P4Operation.CANCELLED, on_operation_cancelled)
    
    print("Starting async operations with detailed info...")
    
    # Example with folder syncing - now you can see which folder is being synced
    folders = ["//games/runner/trailer/alpha/",
               "//games/runner/trailer/beta/",
               "//games/runner/trailer/launch/"]
    
    for folder in folders:
        op_id = p4_client.sync_folders_async([folder])
        print(f"Queued sync for {folder} with operation ID: {op_id}")
    
    # Example with file syncing
    files = ["//depot/some/file1.txt", "//depot/some/file2.txt"]
    sync_files_id = p4_client.sync_files_async(files, revision=123, force=True)
    
    # Example with changelist creation
    changelist_id = p4_client.make_new_changelist_async("My detailed changelist with progress tracking")
    
    # ...existing code...
