import threading
import queue
import time
from enum import Enum
from typing import Callable, Any, Dict, List, Optional
import logging
from functools import wraps

from .p4cmd import P4Client


class OperationStatus(Enum):
    """Enum representing the status of a P4 operation"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class P4Operation:
    """Represents a P4 operation with its metadata"""
    
    # Signal names as class properties for autocomplete and type safety
    STARTED = 'operation_started'
    PROGRESS = 'operation_progress'
    COMPLETED = 'operation_completed'
    FAILED = 'operation_failed'
    CANCELLED = 'operation_cancelled'
    
    def __init__(self, operation_id: str, method_name: str, args: tuple, kwargs: dict):
        self.operation_id = operation_id
        self.method_name = method_name
        self.args = args
        self.kwargs = kwargs
        self.status = OperationStatus.PENDING
        self.result = None
        self.error = None
        self.start_time = None
        self.end_time = None
        self.progress = 0.0
        
    def duration(self) -> Optional[float]:
        """Returns the duration of the operation in seconds, or None if not completed"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
        
    def get_argument(self, index: int, default=None):
        """
        Get a positional argument by index
        
        :param index: Index of the argument
        :param default: Default value if index is out of range
        :return: Argument value or default
        """
        try:
            return self.args[index]
        except IndexError:
            return default
            
    def get_keyword_argument(self, key: str, default=None):
        """
        Get a keyword argument by key
        
        :param key: Keyword argument name
        :param default: Default value if key doesn't exist
        :return: Argument value or default
        """
        return self.kwargs.get(key, default)
        

class ThreadedP4Client:
    """
    A threaded wrapper for P4Client that runs operations in a separate thread
    with a signal system for monitoring operation status.
    """
    
    def __init__(self, perforce_root, user=None, client=None, server=None, silent=True, max_parallel_connections=4):
        """
        Initialize ThreadedP4Client
        
        :param perforce_root: *string* root of your Perforce workspace
        :param user: *string* P4USER, if None will be tried to be found automatically
        :param client: *string* P4CLIENT, if None will be tried to be found automatically
        :param server: *string* P4PORT, if None will be tried to be found automatically
        :param silent: *bool* if True, suppresses error messages
        :param max_parallel_connections: *int* max number of connections to use
        """
        # Initialize the underlying P4Client
        self._p4client = P4Client(perforce_root, user, client, server, silent, max_parallel_connections)
        
        # Threading components
        self._operation_queue = queue.Queue()
        self._worker_thread = None
        self._shutdown_event = threading.Event()
        self._operation_counter = 0
        self._operations = {}  # Store operations by ID
        self._lock = threading.Lock()
        
        # Signal callbacks - using P4Operation constants for consistency
        self._callbacks = {
            P4Operation.STARTED: [],
            P4Operation.PROGRESS: [],
            P4Operation.COMPLETED: [],
            P4Operation.FAILED: [],
            P4Operation.CANCELLED: []
        }
        
        # Start the worker thread
        self._start_worker_thread()
        
        # Expose synchronous properties and methods that don't need threading
        self.perforce_root = self._p4client.perforce_root
        self.user = self._p4client.user
        self.client = self._p4client.client
        self.server = self._p4client.server
        self.depot_root = self._p4client.depot_root
        
    @classmethod
    def from_env(cls, *args, **kwargs):
        """Create ThreadedP4Client from environment variables"""
        return cls(P4Client.from_env(*args, **kwargs).perforce_root, *args, **kwargs)
        
    def _start_worker_thread(self):
        """Start the background worker thread"""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
            
    def _worker_loop(self):
        """Main worker thread loop that processes operations"""
        while not self._shutdown_event.is_set():
            try:
                # Wait for an operation with timeout to allow shutdown checks
                operation = self._operation_queue.get(timeout=1.0)
                if operation is None:  # Shutdown signal
                    break
                    
                self._execute_operation(operation)
                self._operation_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Worker thread error: {e}")
                
    def _execute_operation(self, operation: P4Operation):
        """Execute a single P4 operation"""
        with self._lock:
            operation.status = OperationStatus.RUNNING
            operation.start_time = time.time()
            
        self._emit_signal(P4Operation.STARTED, operation)
        
        try:
            # Get the method from the underlying P4Client
            method = getattr(self._p4client, operation.method_name)
            
            # Execute the method
            result = method(*operation.args, **operation.kwargs)
            
            with self._lock:
                operation.status = OperationStatus.COMPLETED
                operation.result = result
                operation.end_time = time.time()
                operation.progress = 100.0
                
            self._emit_signal(P4Operation.COMPLETED, operation)
            
        except Exception as e:
            with self._lock:
                operation.status = OperationStatus.FAILED
                operation.error = e
                operation.end_time = time.time()
                
            self._emit_signal(P4Operation.FAILED, operation)
            
    def _emit_signal(self, signal_name: str, operation: P4Operation):
        """Emit a signal to all registered callbacks"""
        callbacks = self._callbacks.get(signal_name, [])
        for callback in callbacks:
            try:
                callback(operation)
            except Exception as e:
                logging.error(f"Error in signal callback {signal_name}: {e}")
                
    def _generate_operation_id(self) -> str:
        """Generate a unique operation ID"""
        with self._lock:
            self._operation_counter += 1
            return f"op_{self._operation_counter:06d}"
            
    def _queue_operation(self, method_name: str, *args, **kwargs) -> str:
        """Queue an operation for execution and return its ID"""
        operation_id = self._generate_operation_id()
        operation = P4Operation(operation_id, method_name, args, kwargs)
        
        with self._lock:
            self._operations[operation_id] = operation
            
        self._operation_queue.put(operation)
        return operation_id
        
    def connect_signal(self, signal_name: str, callback: Callable[[P4Operation], None]):
        """
        Connect a callback to a signal
        
        :param signal_name: Name of the signal ('operation_started', 'operation_progress', 
                           'operation_completed', 'operation_failed', 'operation_cancelled')
        :param callback: Function that takes a P4Operation as parameter
        """
        if signal_name not in self._callbacks:
            raise ValueError(f"Unknown signal: {signal_name}")
        self._callbacks[signal_name].append(callback)
        
    def disconnect_signal(self, signal_name: str, callback: Callable[[P4Operation], None]):
        """
        Disconnect a callback from a signal
        
        :param signal_name: Name of the signal
        :param callback: Function to disconnect
        """
        if signal_name in self._callbacks and callback in self._callbacks[signal_name]:
            self._callbacks[signal_name].remove(callback)
            
    def get_operation_status(self, operation_id: str) -> Optional[P4Operation]:
        """
        Get the status of an operation by ID
        
        :param operation_id: ID of the operation
        :return: P4Operation object or None if not found
        """
        with self._lock:
            return self._operations.get(operation_id)
            
    def get_all_operations(self) -> Dict[str, P4Operation]:
        """Get all operations and their statuses"""
        with self._lock:
            return self._operations.copy()
            
    def cancel_operation(self, operation_id: str) -> bool:
        """
        Attempt to cancel an operation (only works if it's still pending)
        
        :param operation_id: ID of the operation to cancel
        :return: True if cancelled, False otherwise
        """
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation and operation.status == OperationStatus.PENDING:
                operation.status = OperationStatus.CANCELLED
                self._emit_signal(P4Operation.CANCELLED, operation)
                return True
        return False
        
    def wait_for_operation(self, operation_id: str, timeout: Optional[float] = None) -> Optional[Any]:
        """
        Wait for an operation to complete and return its result
        
        :param operation_id: ID of the operation to wait for
        :param timeout: Maximum time to wait in seconds
        :return: Operation result or None if timeout/error
        """
        start_time = time.time()
        while True:
            operation = self.get_operation_status(operation_id)
            if not operation:
                return None
                
            if operation.status in [OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.CANCELLED]:
                if operation.status == OperationStatus.COMPLETED:
                    return operation.result
                else:
                    return None
                    
            if timeout and (time.time() - start_time) > timeout:
                return None
                
            time.sleep(0.1)
            
    def wait_for_all_operations(self, timeout: Optional[float] = None):
        """
        Wait for all queued operations to complete
        
        :param timeout: Maximum time to wait in seconds
        :return: True if all operations completed, False if timeout occurred
        """
        if timeout is None:
            # No timeout - wait indefinitely
            try:
                self._operation_queue.join()
                return True
            except:
                return False
        else:
            # With timeout - poll for completion
            start_time = time.time()
            while True:
                # Check if queue is empty (all tasks done)
                if self._operation_queue.unfinished_tasks == 0:
                    return True
                    
                # Check timeout
                if (time.time() - start_time) > timeout:
                    return False
                    
                # Short sleep to avoid busy waiting
                time.sleep(0.1)
            
    def shutdown(self):
        """Shutdown the threaded client and clean up resources"""
        self._shutdown_event.set()
        self._operation_queue.put(None)  # Signal worker to stop
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
            
    # Synchronous methods that don't need threading (quick operations)
    def set_perforce_root(self, root):
        """Set the root of the perforce commands"""
        return self._p4client.set_perforce_root(root)
        
    def set_max_parallel_connections(self, value):
        """Set the number of maximum parallel connections"""
        return self._p4client.set_max_parallel_connections(value)
        
    def get_p4_setting(self, setting):
        """Get a Perforce setting (synchronous)"""
        return self._p4client.get_p4_setting(setting)
        
    def find_p4_client(self):
        """Find P4CLIENT (synchronous)"""
        return self._p4client.find_p4_client()
        
    def find_p4_port(self):
        """Find P4PORT (synchronous)"""
        return self._p4client.find_p4_port()
        
    # Asynchronous methods (potentially long-running operations)
    def run_cmd_async(self, cmd, args=[], file_list=[], use_global_options=True, online_check=True) -> str:
        """Run a P4 command asynchronously"""
        return self._queue_operation('run_cmd', cmd, args, file_list, use_global_options, online_check)
        
    def sync_files_async(self, file_list, revision=-1, verify=True, force=False) -> str:
        """Sync files asynchronously"""
        return self._queue_operation('sync_files', file_list, revision, verify, force)
        
    def sync_folders_async(self, folder_list) -> str:
        """Sync folders recursively asynchronously"""
        return self._queue_operation('sync_folders', folder_list)
        
    def submit_changelist_async(self, changelist="default") -> str:
        """Submit a changelist asynchronously"""
        return self._queue_operation('submit_changelist', changelist)
        
    def files_to_p4files_async(self, file_list, allow_invalid_files=False) -> str:
        """Convert files to P4Files asynchronously"""
        return self._queue_operation('files_to_p4files', file_list, allow_invalid_files)
        
    def folder_to_p4files_async(self, folder, include_subfolders=True, allow_invalid_files=False) -> str:
        """Convert folder to P4Files asynchronously"""
        return self._queue_operation('folder_to_p4files', folder, include_subfolders, allow_invalid_files)
        
    def make_new_changelist_async(self, description) -> str:
        """Make a new changelist asynchronously"""
        return self._queue_operation('make_new_changelist', description)
        
    def move_files_to_changelist_async(self, file_list, changelist="default") -> str:
        """Move files to changelist asynchronously"""
        return self._queue_operation('move_files_to_changelist', file_list, changelist)
        
    def revert_files_async(self, file_list, unchanged_only=False) -> str:
        """Revert files asynchronously"""
        return self._queue_operation('revert_files', file_list, unchanged_only)
        
    # Add more async methods as needed for other P4Client methods
    
    def __getattr__(self, name):
        """
        Fallback to synchronous P4Client methods for any methods not explicitly defined.
        This provides backward compatibility while allowing users to choose async versions.
        """
        if hasattr(self._p4client, name):
            attr = getattr(self._p4client, name)
            if callable(attr):
                # For methods, you can choose to make them async by default or keep them sync
                # Here we keep them synchronous for backward compatibility
                return attr
            else:
                return attr
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
        
    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            self.shutdown()
        except:
            pass
