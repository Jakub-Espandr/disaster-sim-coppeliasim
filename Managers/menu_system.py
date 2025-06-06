# Managers/menu_system.py

import tkinter as tk
from tkinter import ttk, filedialog
from Utils.config_utils import FIELDS
from Utils.scene_utils import restart_disaster_area
from Managers.scene_manager import (
    create_scene, clear_scene, cancel_scene_creation,
    SCENE_START_CREATION, SCENE_CREATION_PROGRESS, 
    SCENE_CREATION_COMPLETED, SCENE_CREATION_CANCELED,
    SCENE_CLEARED
)
from Utils.log_utils import get_logger, DEBUG_L1, DEBUG_L2, DEBUG_L3, LOG_LEVEL_DEBUG, LOG_LEVEL_INFO, LOG_LEVEL_WARNING, LOG_LEVEL_ERROR, LOG_LEVEL_CRITICAL
from Controls.rc_controller_settings import RCControllerSettings

from Managers.Connections.sim_connection import SimConnection
SC = SimConnection.get_instance()

from Core.event_manager import EventManager
EM = EventManager.get_instance()

import math
import json
import time
import psutil
import platform
import threading
from datetime import datetime
import os
import sys
from Tools.scroll_frame import ScrollFrame


class MenuSystem:
    def __init__(self, config: dict, sim_command_queue):
        self.sim_queue = sim_command_queue
        self.sim = SC.sim
        self.config = config
        # Map to hold config UI variables and widgets
        self._config_vars = {}
        self._config_widgets = {}

        # Flag to track UI state
        self._ui_active = True
        
        # Get logger instance
        self.logger = get_logger()
        
        # Track current selected tab
        self._current_tab = "Scene"  # Default tab

        # Subscribe to config updates to sync UI
        EM.subscribe('config/updated', self._on_config_updated_gui)

        self.progress_var = None  # For progress bar

        # Performance tracking
        self._last_ui_update = 0
        self._last_fps_update = 0
        self._frame_times = []
        self._sim_frame_times = []
        self._start_time = time.time()
        self._monitoring_active = False
        self._monitoring_after_id = None
        
        # Set default monitoring state to disabled
        self.config["enable_performance_monitoring"] = False
        
        # Ensure default values for tree spawn interval and bird speed
        if "tree_spawn_interval" not in self.config:
            self.config["tree_spawn_interval"] = 30.0
        if "bird_speed" not in self.config:
            self.config["bird_speed"] = 1.0
            
        # Initialize single-axis mode to disabled by default
        if "single_axis_mode" not in self.config:
            self.config["single_axis_mode"] = False
            
        # Set of currently pressed keys for UI control
        self._ui_pressed_keys = set()

        # Build and style main window
        self.root = tk.Tk()
        self.root.title("Disaster Simulation with Drone Navigation v1.4.0B - HyperDrive Pathway")
        self.root.geometry("700x900")  # Increased width to ensure all tabs are visible
        self.root.configure(bg="#1a1a1a")  # Dark background
        
        # Initialize Tkinter variables after root window is created
        self.control_status_var = tk.StringVar(value="UI Control: Initializing (5x Speed)...")
        
        # Set window icon
        try:
            # Get the absolute path to the assets directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            assets_dir = os.path.join(os.path.dirname(current_dir), 'assets')
            
            # Try to load the icon file
            icon_path = os.path.join(assets_dir, 'icon.ico')
            png_path = os.path.join(assets_dir, 'icon.png')
            
            self.logger.debug_at_level(DEBUG_L2, "MenuSystem", f"Looking for icons in: {assets_dir}")
            self.logger.debug_at_level(DEBUG_L2, "MenuSystem", f"ICO path: {icon_path}")
            self.logger.debug_at_level(DEBUG_L2, "MenuSystem", f"PNG path: {png_path}")
            
            if platform.system() == 'Darwin':  # macOS
                if os.path.exists(png_path):
                    self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Found PNG file, setting icon for macOS")
                    # For macOS, we need to use iconphoto with a PhotoImage
                    icon_image = tk.PhotoImage(file=png_path)
                    self.root.iconphoto(True, icon_image)  # True means apply to all windows
                else:
                    self.logger.warning("MenuSystem", "No PNG file found for macOS")
            else:  # Windows/Linux
                if os.path.exists(icon_path):
                    self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Found ICO file, setting icon")
                    self.root.iconbitmap(icon_path)
                elif os.path.exists(png_path):
                    self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Found PNG file, setting icon")
                    icon_image = tk.PhotoImage(file=png_path)
                    self.root.iconphoto(True, icon_image)
                else:
                    self.logger.warning("MenuSystem", "No icon files found")
        except Exception as e:
            self.logger.error("MenuSystem", f"Error loading icon: {str(e)}")
            
        # Make window resizable with minimum size
        self.root.resizable(True, True)
        self.root.minsize(700, 900)  # Increased minimum width to ensure all tabs are visible
        
        # Add window shadow effect
        self.root.attributes('-alpha', 0.98)  # Slight transparency for modern look
        
        # Configure styles
        self._configure_styles()
        self._build_ui()
        
        # Register for scene-related events
        self._register_event_handlers()
        
        # Center window on screen
        self._center_window()

        # Set up keyboard control from UI
        self._setup_keyboard_control()
        
    # Add keyboard control setup method
    def _setup_keyboard_control(self):
        """Set up keyboard event handling for drone control from UI window"""
        # Map keys to movement directions
        self.key_direction_map = {
            'w': ('forward', 1),
            's': ('forward', -1),
            'a': ('sideward', -1),
            'd': ('sideward', 1),
            'space': ('upward', 1),  # Use 'space' instead of ' ' for Tkinter
            'z': ('upward', -1),
            'q': ('yaw', 1),
            'e': ('yaw', -1),
        }
        
        # Track specific key names
        self.known_keysyms = {
            'space': 'space',
            'w': 'w', 'a': 'a', 's': 's', 'd': 'd',
            'z': 'z', 'q': 'q', 'e': 'e',
            'W': 'w', 'A': 'a', 'S': 's', 'D': 'd',
            'Z': 'z', 'Q': 'q', 'E': 'e'
        }
        
        # Bind key press and release events
        self.root.bind("<KeyPress>", self._on_ui_key_press)
        self.root.bind("<KeyRelease>", self._on_ui_key_release)
        
        # Add specific space key binding
        self.root.bind("<space>", lambda e: self._on_ui_key_press_special('space'))
        self.root.bind("<KeyRelease-space>", lambda e: self._on_ui_key_release_special('space'))
        
        # Bind focus events
        self.root.bind("<FocusIn>", self._on_focus_in)
        self.root.bind("<FocusOut>", self._on_focus_out)
        
        # Schedule regular movement updates based on pressed keys
        self._schedule_movement_updates()
        
        # Make sure we grab focus for keyboard events
        self.root.after(100, self._ensure_focus)
    
    def _on_focus_in(self, event):
        """Handle window gaining focus"""
        self.control_status_var.set("UI Control Active")
        self.control_status_label.configure(foreground="#00FF00")  # Green
        
        # Ensure we don't have any stuck keys from previous state
        self._ui_pressed_keys.clear()
        
        # Stop any existing movement to ensure clean state
        EM.publish('keyboard/move', (0.0, 0.0, 0.0, 8))
        EM.publish('keyboard/rotate', (0.0, 8))
        
        self.logger.info("MenuSystem", "UI control active - window regained focus")
    
    def _on_focus_out(self, event):
        """Handle when the UI loses focus - stop keyboard controls"""
        self.control_status_var.set("UI Control Inactive - Click window to activate")
        self.control_status_label.configure(foreground="#FF3333")  # Red
        
        # Clear currently pressed keys and stop drone movement
        self._ui_pressed_keys.clear()
        
        # Send stop movement events
        EM.publish('keyboard/move', (0.0, 0.0, 0.0, 8))  # 8 = hover
        EM.publish('keyboard/rotate', (0.0, 8))
        
        self.logger.warning("MenuSystem", "UI control inactive - window lost focus")
    
    def _ensure_focus(self):
        """Ensure the window has focus for keyboard events"""
        self.root.focus_force()
        
        # Update status message
        if self.root.focus_get():
            self.control_status_var.set("UI Control Active")
            self.control_status_label.configure(foreground="#00FF00")  # Green
            self.logger.info("MenuSystem", "UI control active - window has focus")
        else:
            self.control_status_var.set("UI Control Inactive - Click window to activate")
            self.control_status_label.configure(foreground="#FF3333")  # Red
            self.logger.warning("MenuSystem", "UI control inactive - window lacks focus")
    
    def _on_ui_key_press(self, event):
        """Handle key press events from UI"""
        # Get the key symbol or character
        key = event.keysym.lower() if hasattr(event, 'keysym') else event.char.lower()
        
        # Map to known key if possible
        if key in self.known_keysyms:
            key = self.known_keysyms[key]
        
        # Ignore if the key is not in our mapping
        if key not in self.key_direction_map:
            self.logger.debug_at_level(DEBUG_L3, "MenuSystem", f"Ignoring unknown key: {key}")
            return
        
        # Add to pressed keys set
        self._ui_pressed_keys.add(key)
        
        # Log key press for debugging
        self.logger.debug_at_level(DEBUG_L3, "MenuSystem", f"UI key press: {key}")
    
    def _on_ui_key_press_special(self, key):
        """Handle special key press events that need specific handling"""
        self._ui_pressed_keys.add(key)
        self.logger.debug_at_level(DEBUG_L3, "MenuSystem", f"UI special key press: {key}")
        return "break"  # Prevent default handling
    
    def _on_ui_key_release(self, event):
        """Handle key release events from UI"""
        # Get the key symbol or character
        key = event.keysym.lower() if hasattr(event, 'keysym') else event.char.lower()
        
        # Map to known key if possible
        if key in self.known_keysyms:
            key = self.known_keysyms[key]
        
        # Remove from pressed keys set if present
        if key in self._ui_pressed_keys:
            self._ui_pressed_keys.discard(key)
            
        # Log key release for debugging
        self.logger.debug_at_level(DEBUG_L3, "MenuSystem", f"UI key release: {key}")
    
    def _on_ui_key_release_special(self, key):
        """Handle special key release events that need specific handling"""
        if key in self._ui_pressed_keys:
            self._ui_pressed_keys.discard(key)
        self.logger.debug_at_level(DEBUG_L3, "MenuSystem", f"UI special key release: {key}")
        return "break"  # Prevent default handling
    
    def _schedule_movement_updates(self):
        """Schedule regular movement updates based on pressed keys"""
        # Process current key state
        self._process_movement()
        
        # Schedule next update (every 20ms for smooth control)
        self.root.after(20, self._schedule_movement_updates)
    
    def _process_movement(self):
        """Process keyboard movement commands and send events"""
        forward = 0  # Forward/backward
        sideward = 0  # Left/right
        upward = 0  # Up/down
        yaw = 0  # Rotation
        
        # Check which keys are pressed
        for key in self._ui_pressed_keys:
            if key == 'w':
                forward += 1
            elif key == 's':
                forward -= 1
            elif key == 'a':
                sideward -= 1
            elif key == 'd':
                sideward += 1
            elif key == 'space':
                upward += 1
            elif key == 'z':
                upward -= 1
            elif key == 'q':
                yaw += 1
            elif key == 'e':
                yaw -= 1
        
        # Apply single-axis movement restriction if enabled
        if self.config.get("single_axis_mode", False):
            # Determine which input has the largest magnitude
            max_input = max(abs(forward), abs(sideward), abs(yaw), abs(upward))
            
            # Only allow the axis with the largest input, zero out all others
            if max_input > 0:
                if abs(forward) == max_input:  # Forward/backward has priority
                    sideward = 0
                    upward = 0
                    yaw = 0
                elif abs(sideward) == max_input:  # Left/right has priority
                    forward = 0
                    upward = 0
                    yaw = 0
                elif abs(yaw) == max_input:  # Rotation has priority
                    forward = 0
                    sideward = 0
                    upward = 0
                elif abs(upward) == max_input:  # Up/down has priority
                    forward = 0
                    sideward = 0
                    yaw = 0
        
        # Get movement parameters from config
        move_step = self.config.get('move_step', 0.2)
        rotate_step = self.config.get('rotate_step_deg', 15.0)
        
        # Increase the movement speed for UI control by 6x
        # We'll also apply a small adjustment factor since we're updating more frequently
        ui_speed_multiplier = 6.0  # 5 times faster for UI control
        smooth_move_step = move_step * ui_speed_multiplier * 0.5
        smooth_rotate_step = math.radians(rotate_step) * 0.5
        
        # Compute action label based on movement
        action_label = 8  # Default hover
        if abs(sideward) > 0.1 or abs(forward) > 0.1 or abs(upward) > 0.1:
            max_dir = max(abs(sideward), abs(forward), abs(upward))
            if max_dir == abs(sideward):
                action_label = 0 if sideward > 0 else 1  # Right/Left
            elif max_dir == abs(forward):
                action_label = 2 if forward > 0 else 3  # Forward/Back
            else:
                action_label = 4 if upward > 0 else 5  # Up/Down
        elif abs(yaw) > 0.01:
            action_label = 6 if yaw > 0 else 7  # Turn Right/Left
        
        # Send movement events if there are active keys
        if self._ui_pressed_keys:
            if forward or sideward or upward:
                EM.publish('keyboard/move', (sideward * smooth_move_step, forward * smooth_move_step, upward * smooth_move_step, action_label))
            
            if yaw:
                EM.publish('keyboard/rotate', (yaw * smooth_rotate_step, action_label))
        
        # Always process movement, which helps ensure smooth control
        # This gets called regularly via _schedule_movement_updates

    def _center_window(self):
        """Center the window on the screen"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _configure_styles(self):
        """Configure modern styles for the application"""
        style = ttk.Style(self.root)
        style.theme_use('clam')
        
        # Configure colors - Modern dark theme with accent colors
        bg_color = "#1a1a1a"  # Dark background
        fg_color = "#ffffff"  # White text
        accent_color = "#00b4d8"  # Modern blue accent
        success_color = "#2ecc71"  # Modern green
        warning_color = "#f1c40f"  # Modern yellow
        error_color = "#e74c3c"  # Modern red
        hover_color = "#2d2d2d"  # Slightly lighter for hover states
        
        # Configure notebook style
        style.configure("TNotebook", background=bg_color, borderwidth=0)
        style.configure("TNotebook.Tab", 
                       background=bg_color,
                       foreground=fg_color,
                       padding=[18, 8],  # Increased horizontal padding for wider tabs
                       font=("Segoe UI", 10, "bold"),
                       justify="center")  # Center text in tabs
        style.map("TNotebook.Tab",
                 background=[("selected", hover_color)],
                 foreground=[("selected", accent_color)])
        
        # Make tabs expand to fill entire width
        style.layout("TNotebook", [("TNotebook.client", {"sticky": "nswe"})])
        style.layout("TNotebook.Tab", [
            ("TNotebook.tab", {
                "sticky": "nswe",  # Make tabs expand in all directions
                "children": [
                    ("TNotebook.padding", {
                        "side": "top",
                        "sticky": "nswe",
                        "children": [
                            ("TNotebook.label", {"side": "top", "sticky": "n", "expand": 1})  # Center-align text with expand=1 and sticky="n"
                        ]
                    })
                ]
            })
        ])
        
        # Configure frame styles
        style.configure("TFrame", background=bg_color)
        style.configure("TLabelframe", 
                       background=bg_color, 
                       foreground=fg_color,
                       borderwidth=1,
                       relief="solid")
        style.configure("TLabelframe.Label", 
                       background=bg_color,
                       foreground=accent_color,
                       font=("Segoe UI", 11, "bold"),
                       padding=[0, 5])
        
        # Configure label styles
        style.configure("TLabel", 
                       background=bg_color,
                       foreground=fg_color,
                       font=("Segoe UI", 10),
                       padding=[5, 2])
        style.configure("Title.TLabel",
                       font=("Segoe UI", 18, "bold"),
                       foreground=accent_color,
                       padding=[0, 10])
        style.configure("Subtitle.TLabel",
                       font=("Segoe UI", 12, "bold"),
                       foreground=fg_color,
                       padding=[0, 5])
        
        # Configure button styles
        style.configure("TButton",
                       background=bg_color,
                       foreground=fg_color,
                       padding=[20, 15],  # Increased padding for larger buttons
                       font=("Segoe UI", 12, "bold"),  # Larger font
                       borderwidth=1,
                       relief="solid",
                       anchor="center",
                       justify="center")
        style.map("TButton",
                 background=[("active", hover_color)],
                 foreground=[("active", accent_color)],
                 relief=[("pressed", "sunken")])
        
        # Configure Apply button style with light green color
        style.configure("Apply.TButton",
                       background="#4CAF50",  # Light green
                       foreground="#ffffff",
                       padding=[20, 15],
                       font=("Segoe UI", 12, "bold"),
                       borderwidth=1,
                       relief="solid")
        style.map("Apply.TButton",
                 background=[("active", "#3E8E41")],  # Darker green on hover
                 foreground=[("active", "#ffffff")],
                 relief=[("pressed", "sunken")])
        
        # Configure scene control button styles with colors
        # Create button - Green
        style.configure("Create.TButton",
                       background=success_color,
                       foreground="#ffffff",
                       padding=[20, 15],  # Increased padding for larger buttons
                       font=("Segoe UI", 12, "bold"),  # Larger font
                       borderwidth=1,
                       width=30,  # Increased width
                       relief="solid")
        style.map("Create.TButton",
                 background=[("active", "#27ae60")],  # Darker green on hover
                 foreground=[("active", "#ffffff")],
                 relief=[("pressed", "sunken")])
                 
        # Clear button - Orange
        style.configure("Clear.TButton",
                       background="#e67e22",  # Orange
                       foreground="#ffffff",
                       padding=[20, 15],  # Increased padding for larger buttons
                       font=("Segoe UI", 12, "bold"),  # Larger font
                       borderwidth=1,
                       width=30,  # Increased width
                       relief="solid")
        style.map("Clear.TButton",
                 background=[("active", "#d35400")],  # Darker orange on hover
                 foreground=[("active", "#ffffff")],
                 relief=[("pressed", "sunken")])
                 
        # Cancel button - Red
        style.configure("Cancel.TButton",
                       background=error_color,
                       foreground="#ffffff",
                       padding=[20, 15],  # Increased padding for larger buttons
                       font=("Segoe UI", 12, "bold"),  # Larger font
                       borderwidth=1,
                       width=30,  # Increased width
                       relief="solid")
        style.map("Cancel.TButton",
                 background=[("active", "#c0392b")],  # Darker red on hover
                 foreground=[("active", "#ffffff")],
                 relief=[("pressed", "sunken")])
        
        # Configure quit button style
        style.configure("Quit.TButton",
                       background=bg_color,
                       foreground=error_color,
                       padding=[15, 10],
                       font=("Segoe UI", 12, "bold"),
                       borderwidth=1,
                       relief="solid")
        style.map("Quit.TButton",
                 background=[("active", hover_color)],
                 foreground=[("active", error_color)],
                 relief=[("pressed", "sunken")])
        
        # Configure entry styles
        style.configure("TEntry",
                       fieldbackground=hover_color,
                       foreground=fg_color,
                       borderwidth=1,
                       relief="solid",
                       font=("Segoe UI", 10),
                       padding=[5, 2])
        
        # Configure checkbutton styles
        style.configure("TCheckbutton",
                       background=bg_color,
                       foreground=fg_color,
                       font=("Segoe UI", 10),
                       padding=[5, 2])
        style.map("TCheckbutton",
                 background=[("active", bg_color)],
                 foreground=[("active", accent_color)],
                 indicatorcolor=[("selected", accent_color), ("!selected", hover_color)],
                 indicatorbackground=[("selected", hover_color), ("!selected", hover_color)],
                 indicatorrelief=[("selected", "flat"), ("!selected", "flat")],
                 indicatorborderwidth=[("selected", 0), ("!selected", 0)],
                 indicatorforeground=[("selected", accent_color), ("!selected", hover_color)])
        
        # Configure progress bar styles with gradients
        style.configure("Red.Horizontal.TProgressbar", 
                       troughcolor=bg_color,
                       background=error_color,
                       bordercolor=accent_color,
                       thickness=10)
        style.configure("Orange.Horizontal.TProgressbar", 
                       troughcolor=bg_color,
                       background=warning_color,
                       bordercolor=accent_color,
                       thickness=10)
        style.configure("Yellow.Horizontal.TProgressbar", 
                       troughcolor=bg_color,
                       background=warning_color,
                       bordercolor=accent_color,
                       thickness=10)
        style.configure("Green.Horizontal.TProgressbar", 
                       troughcolor=bg_color,
                       background=success_color,
                       bordercolor=accent_color,
                       thickness=10)

        # Dark styles specifically for dialogs with white backgrounds
        style.configure("Dark.TFrame", background="#1a1a1a")
        style.configure("Dark.TLabelframe", 
                       background="#1a1a1a", 
                       foreground=fg_color,
                       borderwidth=1,
                       relief="solid")
        style.configure("Dark.TLabelframe.Label", 
                       background="#1a1a1a",
                       foreground=accent_color,
                       font=("Segoe UI", 11, "bold"),
                       padding=[0, 5])

    def _register_event_handlers(self):
        """Set up event handlers for scene-related events"""
        # Scene creation events
        EM.subscribe(SCENE_CREATION_PROGRESS, self._on_scene_progress)
        EM.subscribe(SCENE_CREATION_COMPLETED, self._on_scene_completed)
        EM.subscribe(SCENE_CREATION_CANCELED, self._on_scene_canceled)
        EM.subscribe(SCENE_CLEARED, self._on_scene_cleared)
        
        # Handle scene creation requests from menus
        EM.subscribe('scene/request_creation', self._on_scene_creation_request)
        
        EM.subscribe('simulation/frame', self._on_simulation_frame)
        EM.subscribe('simulation/shutdown', self.cleanup)
        
        # Subscribe to UI update trigger
        EM.subscribe('trigger_ui_update', self._force_ui_update)
        
        # Subscribe to dataset capture complete for victim distance updates
        EM.subscribe('dataset/capture/complete', self._update_victim_indicator)
        
        # Subscribe to victim detection events
        EM.subscribe('victim/detected', self._update_victim_indicator)
        
        # Subscribe to dataset events
        EM.subscribe('dataset/batch/saved', self._on_batch_saved)
        EM.subscribe('dataset/config/updated', self._on_dataset_config_updated)

    def _force_ui_update(self, _):
        """Force the UI to update immediately"""
        try:
            self.root.update()
        except Exception as e:
            if hasattr(self, 'verbose') and self.verbose:
                self.logger.error("MenuSystem", f"Error updating UI: {e}")

    def _on_simulation_frame(self, _):
        """Wrapper method to handle simulation frame events and update the UI safely"""
        try:
            self.root.update()
        except Exception as e:
            self.logger.error("MenuSystem", f"Error updating UI: {e}")

    def _update_tab_widths(self, event=None):
        """Update tab widths to fill the notebook width evenly when the window is resized."""
        try:
            tab_count = self.notebook.index('end')
            if tab_count > 0:
                # Get the current width of the notebook
                notebook_width = self.notebook.winfo_width()
                if notebook_width > 0:
                    # Calculate new tab width (with a small margin)
                    tab_width = max(1, (notebook_width // tab_count) - 2)
                    # Update the style while maintaining centered text
                    style = ttk.Style()
                    style.configure('TNotebook.Tab', width=tab_width, justify="center", anchor="center")
        except Exception as e:
            # Ignore errors during resize
            pass
            
    def _build_ui(self):
        """Build the main UI with tabs for different functionality."""
        # Main container frame with adjusted padding
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create the Notebook (tabbed interface)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Scene tab
        scene_tab = ttk.Frame(self.notebook)
        self.notebook.add(scene_tab, text="Scene")
        self._build_scene_tab(scene_tab)
        
        # Controls tab
        controls_tab = ttk.Frame(self.notebook)
        self.notebook.add(controls_tab, text="Controls")
        self._build_controls_tab(controls_tab)
        
        # Config tab
        config_tab = ttk.Frame(self.notebook)
        self.notebook.add(config_tab, text="Config")
        self._build_config_tab(config_tab)
        
        # Status tab
        status_tab = ttk.Frame(self.notebook)
        self.notebook.add(status_tab, text="Status")
        self._build_status_tab(status_tab)
        
        # Help tab
        help_tab = ttk.Frame(self.notebook)
        self.notebook.add(help_tab, text="Help")
        self._build_help_tab(help_tab)
        
        # Performance tab
        perf_tab = ttk.Frame(self.notebook)
        self.notebook.add(perf_tab, text="Monitor")
        self._build_performance_tab(perf_tab)
        
        # Dataset tab
        dataset_tab = ttk.Frame(self.notebook)
        self.notebook.add(dataset_tab, text="Dataset")
        self._build_dataset_tab(dataset_tab)
        
        # Logging tab
        logging_tab = ttk.Frame(self.notebook)
        self.notebook.add(logging_tab, text="Logging")
        self._build_logging_tab(logging_tab)
        
        # Configure tab stretching - ensure tabs take full width
        self.root.update_idletasks()  # Force geometry update
        tab_count = self.notebook.index('end')
        if tab_count > 0:
            # Set tab width to distribute evenly
            tab_width = self.notebook.winfo_width() // tab_count
            style = ttk.Style()
            style.configure('TNotebook.Tab', width=tab_width, justify="center", anchor="center")
        
        # Bind window resize to update tab widths
        self.root.bind("<Configure>", self._update_tab_widths)
            
        # Connect tab change event
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        
        # Add quit button at the bottom
        quit_frame = ttk.Frame(self.root)
        quit_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        
        quit_btn = ttk.Button(quit_frame, text="Quit Application", 
                           style="Quit.TButton", command=self._quit)
        quit_btn.pack(fill=tk.X)

    def _on_tab_changed(self, event):
        """Handle tab selection change"""
        self._pause_monitoring()  # Always pause first
        
        # Get the current tab index and name
        tab_idx = event.widget.index('current')
        tab_name = event.widget.tab(tab_idx, 'text')
        
        # Update the current tab attribute
        self._current_tab = tab_name
        
        self.logger.debug_at_level(DEBUG_L2, "MenuSystem", f"Tab changed to: {tab_name}")
        
        if tab_name == "Monitor":
            # Resume monitoring only if needed
            if self.config.get("enable_performance_monitoring", False):
                self._resume_monitoring()
        elif tab_name == "Logging":
            # Update logging status when tab is selected
            self._update_logging_status()
        elif tab_name == "Status":
            # Update status indicators
            self._update_victim_indicator({'victim_vec': (0, 0, 0, 0)})
        elif tab_name == "Config":
            # Update config values
            self._on_config_updated_gui(None)
        elif tab_name == "Dataset":
            # Update batch numbers when Dataset tab is selected
            if hasattr(self, '_update_batch_numbers'):
                self._update_batch_numbers()
            
        # Force a single update
        self.root.update_idletasks()

    def _pause_monitoring(self):
        """Pause performance monitoring"""
        if self._monitoring_after_id:
            self.root.after_cancel(self._monitoring_after_id)
            self._monitoring_after_id = None
        self._monitoring_active = False

    def _resume_monitoring(self):
        """Resume performance monitoring"""
        if not self._monitoring_active and self.config.get("enable_performance_monitoring", False):
            self._monitoring_active = True
            self._schedule_ui_update()

    def _schedule_ui_update(self):
        """Schedule the next UI update with optimized timing"""
        # Cancel any existing scheduled update
        if self._monitoring_after_id:
            self.root.after_cancel(self._monitoring_after_id)
            self._monitoring_after_id = None
        
        # Only schedule new update if monitoring is enabled
        if self.config.get("enable_performance_monitoring", False):
            current_time = time.time()
            self._frame_times.append(current_time)
            
            # Only update the UI if we're on the Monitor tab
            if self._current_tab == "Monitor":
                if current_time - self._last_ui_update >= 0.1:  # 100ms update interval
                    self._last_ui_update = current_time
                    self._update_performance_metrics()
            
            # Schedule next update regardless of current tab
            self._monitoring_after_id = self.root.after(100, self._schedule_ui_update)
            self._monitoring_active = True
        else:
            # Only clear metrics if monitoring is disabled
            self._monitoring_active = False
            self._clear_performance_metrics()

    def _safe_button_action(self, action_func):
        """
        Wrapper for button actions to prevent space key from triggering them.
        This prevents accidental scene operations when using space for drone movement.
        """
        def safe_action(*args, **kwargs):
            # Check if space key is currently pressed
            if 'space' in self._ui_pressed_keys:
                self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Ignoring button action triggered by space key")
                return
            # Call the original action function
            return action_func(*args, **kwargs)
        return safe_action

    def _build_scene_tab(self, parent):
        # Title with modern styling
        title_frame = ttk.Frame(parent)
        title_frame.pack(fill="x", pady=(0, 20))
        ttk.Label(title_frame, text="Drone Search & Rescue Simulator", style="Title.TLabel").pack()
        
        # Progress bar container with modern styling
        progress_frame = ttk.Frame(parent)
        progress_frame.pack(fill="x", pady=10)
        
        # Progress bar for scene creation with enhanced styling
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, 
                                          variable=self.progress_var, 
                                          maximum=1.0,
                                          style="Green.Horizontal.TProgressbar",
                                          mode='determinate')
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_bar.pack_forget()  # Hide initially
        
        # Status label with enhanced styling
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill="x", pady=10)
        self.status_label = ttk.Label(status_frame, 
                                    text="", 
                                    style="Subtitle.TLabel",
                                    wraplength=400)  # Allow text wrapping
        self.status_label.pack(pady=5)
        
        # Create scene with event-driven approach
        def create_scene_with_event():
            # Check if this was triggered by a space key press (which should be ignored)
            # This prevents accidental scene creation when using space for drone movement
            if 'space' in self._ui_pressed_keys:
                self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Ignoring scene creation triggered by space key")
                return
                
            # Apply all config changes first to ensure latest values are used
            self._apply_all_config_changes()  # Apply all config changes from UI
            
            # Ensure we have explicit int values for all static object counts to avoid any type issues
            self.config["num_trees"] = int(self.config.get("num_trees", 0))
            self.config["num_rocks"] = int(self.config.get("num_rocks", 0))
            self.config["num_bushes"] = int(self.config.get("num_bushes", 0))
            self.config["num_foliage"] = int(self.config.get("num_foliage", 0))
            
            # Also ensure dynamic object settings are explicitly converted to the right types
            self.config["num_birds"] = int(self.config.get("num_birds", 10))
            self.config["num_falling_trees"] = int(self.config.get("num_falling_trees", 5))
            self.config["tree_spawn_interval"] = float(self.config.get("tree_spawn_interval", 30.0))
            self.config["bird_speed"] = float(self.config.get("bird_speed", 1.0))
            
            # Disable all buttons during scene creation
            for btn in self.scene_buttons:
                if "Cancel" not in btn["text"]:
                    btn.configure(state="disabled")
                else:
                    # Enable the cancel button during scene creation
                    btn.configure(state="normal")
            
            # Show progress bar with animation
            self.progress_bar.pack(fill="x", pady=5)
            self.progress_var.set(0.0)
            self.status_label.configure(text="Creating scene...", foreground="#00b4d8")
            
            # Log the configuration for debugging
            self.logger.info("MenuSystem", f"Creating scene with config: "
                            f"{self.config['num_trees']} static trees, "
                            f"{self.config['num_rocks']} rocks, "
                            f"{self.config['num_bushes']} bushes, "
                            f"{self.config['num_foliage']} foliage elements, "
                            f"{self.config['num_birds']} birds, "
                            f"{self.config['num_falling_trees']} falling trees")
            
            # Start scene creation via event system
            create_scene(self.config)
        
        # Restart scene using event-based approach
        def restart_scene():
            # Apply all changes including dynamic objects before restarting
            self._apply_all_changes()
            self.status_label.configure(text="Restarting scene...", foreground="#f1c40f")
            restart_disaster_area(self.config)
            
        # Clear scene using event-based approach with confirmation
        def clear_scene_action():
            # Create confirmation dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Confirm Clear")
            dialog.geometry("300x150")
            dialog.configure(bg="#1a1a1a")
            dialog.transient(self.root)  # Make dialog modal
            dialog.grab_set()  # Make dialog modal
            
            # Center dialog on parent window
            dialog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
            dialog.geometry(f"+{x}+{y}")
            
            # Add padding frame
            frame = ttk.Frame(dialog, padding=20)
            frame.pack(expand=True, fill="both")
            
            # Warning message
            ttk.Label(frame, 
                     text="Are you sure you want to clear the environment?",
                     style="Subtitle.TLabel",
                     wraplength=250).pack(pady=(0, 20))
            
            # Buttons frame
            btn_frame = ttk.Frame(frame)
            btn_frame.pack(fill="x", pady=(0, 10))
            
            # Create a style specifically for these confirmation buttons
            style = ttk.Style()
            btn_style = "Confirmation.TButton"
            style.configure(btn_style, 
                           padding=[10, 10], 
                           font=("Segoe UI", 11, "bold"),
                           anchor="center",
                           justify="center")
            
            # Yes button
            yes_btn = ttk.Button(btn_frame, 
                              text="Yes, Clear",
                              command=lambda: self._confirm_clear(dialog),
                              style=btn_style,
                              compound="center")
            yes_btn.pack(side="left", expand=True, padx=(0, 5), fill="both", ipady=5)
            
            # No button
            no_btn = ttk.Button(btn_frame,
                             text="No, Cancel",
                             command=dialog.destroy,
                             style=btn_style,
                             compound="center")
            no_btn.pack(side="left", expand=True, padx=(5, 0), fill="both", ipady=5)
        
        # Cancel ongoing scene creation 
        def cancel_creation():
            cancel_scene_creation()
            self.status_label.configure(text="Canceling scene creation...", foreground="#e74c3c")
        
        # Scene control buttons with enhanced styling
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill="x", pady=10)
        
        # Center frame for buttons
        center_frame = ttk.Frame(button_frame)
        center_frame.pack(anchor="center")
        
        # Create a container for the vertically arranged buttons
        buttons_container = ttk.Frame(center_frame)
        buttons_container.pack(pady=15)
        
        self.scene_buttons = []
        
        # Create Environment button (Green)
        create_btn = ttk.Button(
            buttons_container, 
            text="Create Environment", 
            command=self._safe_button_action(create_scene_with_event),
            style="Create.TButton"
        )
        create_btn.grid(row=0, column=0, padx=10, pady=8)
        self.scene_buttons.append(create_btn)
        
        # Clear Environment button (Orange)
        clear_btn = ttk.Button(
            buttons_container, 
            text="Clear Environment", 
            command=self._safe_button_action(clear_scene_action),
            style="Clear.TButton"
        )
        clear_btn.grid(row=1, column=0, padx=10, pady=8)
        self.scene_buttons.append(clear_btn)
        
        # Cancel Creating Environment button (Red)
        cancel_btn = ttk.Button(
            buttons_container, 
            text="Cancel Creating", 
            command=self._safe_button_action(cancel_creation),
            style="Cancel.TButton"
        )
        cancel_btn.grid(row=2, column=0, padx=10, pady=8)
        
        # Initially disable the Cancel button since creation is not in progress
        cancel_btn.configure(state="disabled")
        self.scene_buttons.append(cancel_btn)
            
        # Add visual separator
        separator = ttk.Separator(parent, orient='horizontal')
        separator.pack(fill='x', pady=20)

    def _confirm_clear(self, dialog):
        """Handle confirmed clear environment action"""
        dialog.destroy()
        self.status_label.configure(text="Clearing scene...", foreground="#e74c3c")
        clear_scene()

    def _build_config_tab(self, parent):
        # Create a ScrollFrame for the config options
        scroll_frame = ScrollFrame(parent, bg="#0a0a0a")
        scroll_frame.pack(fill="both", expand=True)
        
        # Get the scrollable frame to add content to
        scrollable_frame = scroll_frame.scrollable_frame
        
        # Title
        ttk.Label(scrollable_frame, text="Configuration", style="Title.TLabel").pack(pady=(0,20))
        
        # Dynamic Objects Section with centered title
        dynamic_frame = ttk.LabelFrame(scrollable_frame, text="Dynamic Objects", padding=15, labelanchor="n")
        dynamic_frame.pack(fill="x", pady=10, padx=5)
        
        # Falling Trees control
        trees_frame = ttk.Frame(dynamic_frame)
        trees_frame.pack(fill="x", pady=2)
        ttk.Label(trees_frame, text="Number of Falling Trees:", width=25, style="TLabel", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        trees_var = tk.StringVar(value=str(self.config.get("num_falling_trees", 5)))
        trees_entry = ttk.Entry(trees_frame, textvariable=trees_var, width=20)
        trees_entry.pack(side="left", fill="x", expand=True)
        trees_entry.bind('<Return>', lambda e: self._update_config("num_falling_trees", trees_var.get()))
        trees_entry.bind('<FocusOut>', lambda e: self._update_config("num_falling_trees", trees_var.get()))
        self._config_vars["num_falling_trees"] = trees_var
        self._config_widgets["num_falling_trees"] = trees_entry
        
        # Tree Spawn Interval control
        spawn_frame = ttk.Frame(dynamic_frame)
        spawn_frame.pack(fill="x", pady=2)
        ttk.Label(spawn_frame, text="Tree Spawn Interval (s):", width=25, style="TLabel").pack(side="left", padx=(0, 10))
        spawn_var = tk.StringVar(value=str(self.config.get("tree_spawn_interval", 30.0)))
        spawn_entry = ttk.Entry(spawn_frame, textvariable=spawn_var, width=20)
        spawn_entry.pack(side="left", fill="x", expand=True)
        spawn_entry.bind('<Return>', lambda e: self._update_config("tree_spawn_interval", spawn_var.get()))
        spawn_entry.bind('<FocusOut>', lambda e: self._update_config("tree_spawn_interval", spawn_var.get()))
        self._config_vars["tree_spawn_interval"] = spawn_var
        self._config_widgets["tree_spawn_interval"] = spawn_entry

        # Birds control
        birds_frame = ttk.Frame(dynamic_frame)
        birds_frame.pack(fill="x", pady=2)
        ttk.Label(birds_frame, text="Number of Birds:", width=25, style="TLabel", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        birds_var = tk.StringVar(value=str(self.config.get("num_birds", 10)))
        birds_entry = ttk.Entry(birds_frame, textvariable=birds_var, width=20)
        birds_entry.pack(side="left", fill="x", expand=True)
        birds_entry.bind('<Return>', lambda e: self._update_config("num_birds", birds_var.get()))
        birds_entry.bind('<FocusOut>', lambda e: self._update_config("num_birds", birds_var.get()))
        self._config_vars["num_birds"] = birds_var
        self._config_widgets["num_birds"] = birds_entry

        # Bird Speed control
        bird_speed_frame = ttk.Frame(dynamic_frame)
        bird_speed_frame.pack(fill="x", pady=2)
        ttk.Label(bird_speed_frame, text="Bird Movement Speed:", width=25, style="TLabel", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        bird_speed_var = tk.StringVar(value=str(self.config.get("bird_speed", 1.0)))
        bird_speed_entry = ttk.Entry(bird_speed_frame, textvariable=bird_speed_var, width=20)
        bird_speed_entry.pack(side="left", fill="x", expand=True)
        bird_speed_entry.bind('<Return>', lambda e: self._update_config("bird_speed", bird_speed_var.get()))
        bird_speed_entry.bind('<FocusOut>', lambda e: self._update_config("bird_speed", bird_speed_var.get()))
        self._config_vars["bird_speed"] = bird_speed_var
        self._config_widgets["bird_speed"] = bird_speed_entry
        
        # Keep Fallen Trees toggle
        keep_trees_frame = ttk.Frame(dynamic_frame)
        keep_trees_frame.pack(fill="x", pady=5)
        ttk.Label(keep_trees_frame, text="Keep Fallen Trees:", width=25, style="TLabel", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        keep_trees_var = tk.BooleanVar(value=self.config.get("keep_fallen_trees", False))
        keep_trees_chk = ttk.Checkbutton(keep_trees_frame, variable=keep_trees_var)
        keep_trees_chk.pack(side="left", fill="x", expand=True)
        keep_trees_var.trace_add('write', lambda *_: self._update_config("keep_fallen_trees", keep_trees_var.get()))
        self._config_vars["keep_fallen_trees"] = keep_trees_var
        self._config_widgets["keep_fallen_trees"] = keep_trees_chk
        
        # Add a tooltip or help text for the keep fallen trees option
        keep_trees_info = ttk.Label(dynamic_frame, text="Note: When checked, fallen trees will stay on the ground instead of being removed when new trees spawn", 
                                   style="Small.TLabel", foreground="#aaaaaa")
        keep_trees_info.pack(fill="x", padx=10, pady=(0, 5))

        # Environment Settings Section with centered title
        env_frame = ttk.LabelFrame(scrollable_frame, text="Environment Settings", padding=15, labelanchor="n")
        env_frame.pack(fill="x", pady=10, padx=5)
        
        # Add static tree settings first in Environment Settings
        static_trees_frame = ttk.Frame(env_frame)
        static_trees_frame.pack(fill="x", pady=2)
        ttk.Label(static_trees_frame, text="Number of Static Trees:", width=25, style="TLabel", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        static_trees_var = tk.StringVar(value=str(self.config.get("num_trees", 0)))
        static_trees_entry = ttk.Entry(static_trees_frame, textvariable=static_trees_var, width=20)
        static_trees_entry.pack(side="left", fill="x", expand=True)
        static_trees_entry.bind('<Return>', lambda e: self._update_config("num_trees", static_trees_var.get()))
        static_trees_entry.bind('<FocusOut>', lambda e: self._update_config("num_trees", static_trees_var.get()))
        self._config_vars["num_trees"] = static_trees_var
        self._config_widgets["num_trees"] = static_trees_entry
        
        # Add other environment-related fields
        env_fields = [f for f in FIELDS if f['key'] in ['num_rocks', 'num_bushes', 'num_foliage']]
        for field in env_fields:
            key, desc, typ = field['key'], field['desc'], field['type']
            frame = ttk.Frame(env_frame)
            frame.pack(fill="x", pady=2)
            
            # Make specific labels bold
            if key in ['num_rocks', 'num_bushes', 'num_foliage']:
                label = ttk.Label(frame, text=desc+":", width=25, style="TLabel", font=("Segoe UI", 10, "bold"))
            else:
                label = ttk.Label(frame, text=desc+":", width=25, style="TLabel")
            label.pack(side="left", padx=(0, 10))
            
            if typ is bool:
                var = tk.BooleanVar(value=self.config.get(key, False))
                chk = ttk.Checkbutton(frame, variable=var)
                chk.pack(side="left", fill="x", expand=True)
                var.trace_add('write', lambda *_, k=key, v=var: self._update_config(k, v.get()))
                widget = chk
            else:
                var = tk.StringVar(value=str(self.config.get(key, '')))
                ent = ttk.Entry(frame, textvariable=var, width=20)
                ent.pack(side="left", fill="x", expand=True)
                ent.bind('<Return>', lambda e, k=key, v=var: self._update_config(k, v.get()))
                ent.bind('<FocusOut>', lambda e, k=key, v=var: self._update_config(k, v.get()))
                widget = ent
            self._config_vars[key] = var
            self._config_widgets[key] = widget
            
        # Simulation Settings Section with centered title
        sim_frame = ttk.LabelFrame(scrollable_frame, text="Simulation Settings", padding=15, labelanchor="n")
        sim_frame.pack(fill="x", pady=10, padx=5)
        
        # Add simulation-related fields
        sim_fields = [f for f in FIELDS if f['key'] not in [
            'num_rocks', 'num_bushes', 'num_foliage', 
            'num_birds', 'num_falling_trees', 'tree_spawn_interval', 
            'num_trees', 'rc_sensitivity', 'bird_speed'
        ]]
        for field in sim_fields:
            key, desc, typ = field['key'], field['desc'], field['type']
            frame = ttk.Frame(sim_frame)
            frame.pack(fill="x", pady=2)
            
            # Make area size label bold
            if key == 'area_size':
                label = ttk.Label(frame, text=desc+":", width=25, style="TLabel", font=("Segoe UI", 10, "bold"))
            else:
                label = ttk.Label(frame, text=desc+":", width=25, style="TLabel")
            label.pack(side="left", padx=(0, 10))
            
            if typ is bool:
                var = tk.BooleanVar(value=self.config.get(key, False))
                chk = ttk.Checkbutton(frame, variable=var)
                chk.pack(side="left", fill="x", expand=True)
                var.trace_add('write', lambda *_, k=key, v=var: self._update_config(k, v.get()))
                widget = chk
            else:
                var = tk.StringVar(value=str(self.config.get(key, '')))
                ent = ttk.Entry(frame, textvariable=var, width=20)
                ent.pack(side="left", fill="x", expand=True)
                ent.bind('<Return>', lambda e, k=key, v=var: self._update_config(k, v.get()))
                ent.bind('<FocusOut>', lambda e, k=key, v=var: self._update_config(k, v.get()))
                widget = ent
            self._config_vars[key] = var
            self._config_widgets[key] = widget
            
        # Add a single "Apply Changes" button to handle all changes
        apply_btn = ttk.Button(scrollable_frame, text="Apply Changes", 
                              command=self._apply_all_changes,
                              style="Apply.TButton")
        apply_btn.pack(fill="x", pady=(15, 5), padx=5)

        # Add Save/Load buttons
        save_load_frame = ttk.Frame(scrollable_frame)
        save_load_frame.pack(fill="x", pady=(5, 15), padx=5)
        
        save_btn = ttk.Button(save_load_frame, text="Save Settings", 
                             command=self._save_config)
        save_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        load_btn = ttk.Button(save_load_frame, text="Load Settings", 
                             command=self._load_config)
        load_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))
        
        # Note: Scrolling is now handled by the ScrollFrame class
        # No need for manual scroll event bindings or resize handlers

    def _apply_all_changes(self):
        """Apply all changes including dynamic objects"""
        try:
            # Apply regular config changes
            self._apply_all_config_changes()
            
            # Get and validate dynamic object values
            num_birds = max(0, int(self._config_vars["num_birds"].get()))
            num_trees = max(0, int(self._config_vars["num_falling_trees"].get()))
            tree_spawn = max(5.0, float(self._config_vars["tree_spawn_interval"].get()))
            bird_speed = max(0.1, min(5.0, float(self._config_vars["bird_speed"].get())))  # Limit speed between 0.1 and 5.0
            keep_fallen_trees = bool(self._config_vars["keep_fallen_trees"].get())
            
            # Update the config
            self.config["num_birds"] = num_birds
            self.config["num_falling_trees"] = num_trees
            self.config["tree_spawn_interval"] = tree_spawn
            self.config["bird_speed"] = bird_speed
            self.config["keep_fallen_trees"] = keep_fallen_trees
            
            # Explicitly publish events for movement settings to ensure they're applied
            EM.publish('config/updated', 'move_step')
            EM.publish('config/updated', 'rotate_step_deg')
            
            # Update status
            self.status_label.configure(text="All settings applied successfully")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            
            self.logger.info("MenuSystem", f"Applied all settings: move_step={self.config.get('move_step', 0.0):.2f}")
            
            return True
        except Exception as e:
            self.status_label.configure(text=f"Error applying settings: {e}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            self.logger.error("MenuSystem", f"Error applying settings: {e}")
            return False

    def _apply_all_config_changes(self):
        """Apply all changes to the configuration."""
        for key, var in self._config_vars.items():
            self._update_config(key, var.get())
            
        # Provide feedback to the user
        self.status_label.configure(text="Configuration updated!")
        self.root.after(1000, lambda: self.status_label.configure(text=""))

    def _update_config(self, key, value):
        # convert value to proper type and update
        for field in FIELDS:
            if field['key'] == key:
                typ = field['type']
                try:
                    # Special handling for move_step to round to two decimal places (changed from 1 to 2)
                    if key == "move_step" and typ is float:
                        try:
                            # Make sure we don't set a zero value if a non-zero value already exists
                            new_value = float(value)
                            if new_value == 0.0 and key in self.config and self.config[key] > 0:
                                self.logger.info("MenuSystem", f"Preserving non-zero value for {key}: {self.config[key]}")
                            else:
                                # Round to 2 decimal places to preserve values like 0.05
                                self.config[key] = round(new_value, 2)
                                self.logger.info("MenuSystem", f"Set value for {key}: {self.config[key]}")
                        except ValueError:
                            # If conversion fails, use the current value or 0.2 as default
                            self.config[key] = self.config.get(key, 0.2)
                    elif typ is int:
                        # Handle conversion of floating-point strings to integers
                        try:
                            # First convert to float to handle values like "10.0"
                            float_value = float(value)
                            # Then convert to int
                            self.config[key] = int(float_value)
                        except ValueError as e:
                            self.logger.error("MenuSystem", f"Error converting {value} to int: {e}")
                            # Keep the current value if conversion fails
                            if key in self.config:
                                self.logger.info("MenuSystem", f"Keeping current value for {key}: {self.config[key]}")
                    else:
                        self.config[key] = typ(value)
                    EM.publish('config/updated', key)
                except Exception as e:
                    self.logger.error("MenuSystem", f"Error updating configuration {key}: {e}")
                break

    def _on_config_updated_gui(self, key):
        """
        Handle external or internal config updates and sync GUI elements.
        key: the configuration key that was updated.
        """
        # Update the corresponding variable
        if key in self._config_vars:
            var = self._config_vars[key]
            new_val = self.config.get(key)
            # Set variable (convert to string for non-bool)
            if isinstance(var, tk.StringVar):
                var.set(str(new_val))
            else:
                var.set(bool(new_val))
            # Visual feedback: highlight updated widget
            widget = self._config_widgets.get(key)
            if widget:
                try:
                    widget.configure(background='lightyellow')
                    # revert after short delay
                    widget.after(800, lambda w=widget: w.configure(background='white'))
                except Exception:
                    pass
            
            # Update monitoring status if the key is enable_performance_monitoring
            if key == "enable_performance_monitoring":
                # Restart or stop monitoring based on new value
                if new_val and not self._monitoring_active:
                    self._schedule_ui_update()
                elif not new_val and self._monitoring_active:
                    self._clear_performance_metrics()
            
            # Update single-axis mode if needed
            elif key == "single_axis_mode" and hasattr(self, 'single_axis_mode_var'):
                self.single_axis_mode_var.set(self.config.get('single_axis_mode', False))
        else:
            # If key is None or unknown, refresh all
            for k, var in self._config_vars.items():
                val = self.config.get(k)
                if isinstance(var, tk.StringVar):
                    var.set(str(val))
                else:
                    var.set(bool(val))
                    
            # Also update single-axis mode if available
            if hasattr(self, 'single_axis_mode_var'):
                self.single_axis_mode_var.set(self.config.get('single_axis_mode', False))

    def _quit(self):
        """Clean shutdown of the application"""
        try:
            # Stop any movement before closing
            EM.publish('keyboard/move', (0.0, 0.0, 0.0, 8))  # 8 = hover
            EM.publish('keyboard/rotate', (0.0, 8))
            
            self.logger.info("MenuSystem", "Shutting down application...")
            
            # Create dialog window
            dialog = tk.Toplevel(self.root)
            dialog.title("Confirm Exit")
            dialog.geometry("360x180")
            dialog.transient(self.root)  # Set to be on top of the main window
            dialog.grab_set()  # Modal
            
            # Center on parent
            dialog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
            dialog.geometry(f"+{x}+{y}")
            
            # Content
            content_frame = ttk.Frame(dialog, padding=20)
            content_frame.pack(fill=tk.BOTH, expand=True)
            
            message = ttk.Label(
                content_frame, 
                text="Are you sure you want to exit?\nThis will close the simulator.",
                font=("Segoe UI", 11),
                wraplength=300,
                justify=tk.CENTER
            )
            message.pack(pady=(0, 20))
            
            button_frame = ttk.Frame(content_frame)
            button_frame.pack(fill=tk.X)
            
            cancel_btn = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
            cancel_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
            
            confirm_btn = ttk.Button(
                button_frame, 
                text="Exit", 
                style="Quit.TButton",
                command=lambda: self._confirm_quit(dialog)
            )
            confirm_btn.pack(side=tk.RIGHT, padx=5, expand=True, fill=tk.X)
        except Exception as e:
            self.logger.error("MenuSystem", f"Error during application shutdown: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))

    def _confirm_quit(self, dialog):
        """Handle confirmed quit action"""
        dialog.destroy()
        self.cleanup()
        EM.publish('simulation/shutdown', None)
        
        # Force application to quit in case there are hanging threads
        if hasattr(self, 'root') and self.root:
            # Set a force-quit timer in case normal exit fails
            # Note: after() schedules task, but we need to immediately start quitting process
            self.root.after(500, lambda: os._exit(0))
            
            # Try normal exit first
            try:
                self.root.quit()
                self.root.destroy()
            except Exception as e:
                self.logger.error("MenuSystem", f"Error during application shutdown: {e}")
                # If we reach here, the force-quit will still happen via the scheduled after() call

    def _on_scene_progress(self, data):
        """Update the progress bar and status label when scene creation progresses."""
        def update_ui():
            progress = data.get('progress', 0.0)
            current_category = data.get('current_category', '')
            completed_objects = data.get('completed_objects', 0)
            total_objects = data.get('total_objects', 0)
            
            # Ensure the progress bar is visible
            if not self.progress_bar.winfo_ismapped():
                self.progress_bar.pack(fill="x", pady=5)
                self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Progress bar made visible")
            
            # Set progress bar value
            self.progress_var.set(progress)
            
            # Format appropriate message based on creation state
            if current_category == 'complete':
                message = f"Scene created - {total_objects}/{total_objects} elements"
            else:
                # Format the category name nicely (capitalize)
                category_display = current_category.capitalize()
                message = f"Creating scene - {category_display}: {completed_objects}/{total_objects} elements"
            
            # Update status label
            self.status_label.configure(text=message)
            
            # Update button states
            for i, btn in enumerate(self.scene_buttons):
                if i == 2:  # Cancel button is index 2
                    btn.configure(state="normal")  # Enable the cancel button during creation
                else:
                    btn.configure(state="disabled")  # Disable other buttons during creation
            
            # Force the UI to update
            self.root.update_idletasks()
            
        # Schedule UI update in the main thread
        self.root.after(0, update_ui)
        
    def _on_scene_completed(self, _):
        """Handle scene creation completion."""
        def update_ui():
            self.status_label.configure(text="Scene creation completed!")
            # Re-enable normal buttons and specifically disable the Cancel button
            for i, btn in enumerate(self.scene_buttons):
                if i == 2:  # Cancel button is index 2
                    btn.configure(state="disabled")  # Disable the cancel button
                else:
                    btn.configure(state="normal")  # Enable other buttons
            self.progress_bar.pack_forget()
            
            # Disable the Remove Batches button when scene is active
            if hasattr(self, 'remove_batches_btn'):
                self.remove_batches_btn.configure(state="disabled")
                
            # Update simulation stats
            self._update_simulation_stats()
            
            # Update batch numbers to reflect the new scene's batch number
            if hasattr(self, '_update_batch_numbers'):
                self.root.after(500, self._update_batch_numbers)  # slight delay to let files update
        
        # Schedule the update on the main thread
        self.root.after(0, update_ui)
        
    def _on_scene_canceled(self, _):
        """Handle scene creation cancellation with error handling"""
        def update_ui():
            try:
                self.status_label.configure(text="Scene creation canceled", foreground="white")
                self.progress_var.set(0.0)
                self.progress_bar.pack_forget()
                
                # Re-enable all buttons except Cancel
                for btn in self.scene_buttons:
                    if "Cancel" in btn["text"]:
                        btn.configure(state="disabled")
                    else:
                        btn.configure(state="normal")
            except Exception as e:
                self.logger.error("MenuSystem", f"Error updating UI after scene canceled: {e}")
        
        # Schedule UI update on the main thread
        self.root.after(0, update_ui)
        
    def _on_scene_cleared(self, _):
        """Handle scene cleared event by updating UI state"""
        def update_ui():
            try:
                # Reset status label
                if hasattr(self, 'status_label'):
                    self.status_label.configure(text="Scene cleared", foreground="white")
                
                # Reset victim indicators
                if hasattr(self, 'distance_var'):
                    self.distance_var.set("Not detected")
                
                if hasattr(self, 'elevation_var'):
                    self.elevation_var.set("Not detected")
                
                if hasattr(self, 'direction_canvas'):
                    self.direction_canvas.delete("all")  # Clear the direction indicator
                
                # Re-enable scene control buttons
                if hasattr(self, 'scene_buttons'):
                    for btn in self.scene_buttons:
                        btn.configure(state="normal")
                        
                # Enable the Remove Batches button if it exists
                if hasattr(self, 'remove_batches_btn'):
                    self.remove_batches_btn.configure(state="normal")
                    
                # Update simulation stats
                if hasattr(self, '_update_simulation_stats'):
                    self._update_simulation_stats()
                    
            except Exception as e:
                self.logger.error("MenuSystem", f"Error updating UI after scene clear: {e}")
        
        # Schedule UI update on the main thread
        self.root.after(0, update_ui)

    def _on_scene_creation_request(self, config=None):
        """
        Handle a scene creation request from the menu system.
        This gets triggered when the user selects 'Create disaster area' from the main menu.
        """
        # Check if this was triggered by a space key press (which should be ignored)
        if 'space' in self._ui_pressed_keys:
            self.logger.debug_at_level(DEBUG_L1, "MenuSystem", "Ignoring scene creation triggered by space key")
            return
            
        # Apply all configuration changes first
        self._apply_all_config_changes()
        
        # Use provided config or fall back to the current config
        if config is None:
            config = self.config
            
        # Disable buttons except for the Cancel button during scene creation
        for i, btn in enumerate(self.scene_buttons):
            if i == 2:  # Cancel button is index 2
                btn.configure(state="normal")  # Enable the cancel button
            else:
                btn.configure(state="disabled")  # Disable other buttons
        
        # Show progress bar
        self.progress_bar.pack(fill="x", pady=5)
        self.progress_var.set(0.0)
        self.status_label.configure(text="Creating scene...")
        
        # Start scene creation via event
        create_scene(config)

    def _update_victim_indicator(self, data):
        """Update the victim distance and direction indicator based on capture data"""
        # Add debug logging to see what data is coming in
        self.logger.debug_at_level(DEBUG_L1, "MenuSystem", f"Received victim data: {data}")
        
        # Extract victim vector data (dx, dy, dz) and distance
        if 'victim_vec' not in data:
            self.logger.warning("MenuSystem", "Missing victim_vec in update data")
            return
            
        victim_vec = data.get('victim_vec', (0, 0, 0))
        distance = data.get('distance', 0)
        
        # Validate the vector format
        if not isinstance(victim_vec, tuple) or len(victim_vec) != 3:
            self.logger.debug_at_level(DEBUG_L1, "MenuSystem", f"Invalid victim vector format: {type(victim_vec)}, len: {len(victim_vec) if hasattr(victim_vec, '__len__') else 'N/A'}")
            return
            
        # Unpack victim vector data
        try:
            dx, dy, dz = victim_vec
            self.logger.debug_at_level(DEBUG_L1, "MenuSystem", f"Processing victim data: dx={dx}, dy={dy}, dz={dz}, distance={distance}")
        except Exception as e:
            self.logger.error("MenuSystem", f"Error unpacking victim vector: {e}")
            return
        
        # Update UI safely
        def update_ui():
            # Update distance text
            if distance <= 0:
                self.distance_var.set("Not detected")
                self.elevation_var.set("Not detected")
            else:
                self.distance_var.set(f"{distance:.2f} meters")
                
                # Update elevation text with simple numerical format
                if abs(dz) < 0.1:  # If very close to level
                    self.elevation_var.set("Same level (±0.1m)")
                    self.elevation_label.configure(foreground="green")
                elif dz > 0:
                    self.elevation_var.set(f"{dz:.2f}m above drone")
                    # Color based on how much higher (harder to reach)
                    if dz > 3:
                        self.elevation_label.configure(foreground="red")
                    else:
                        self.elevation_label.configure(foreground="orange")
                else:  # dz < 0
                    self.elevation_var.set(f"{abs(dz):.2f}m below drone")
                    # Color based on how much lower (easier to spot)
                    if abs(dz) > 3:
                        self.elevation_label.configure(foreground="orange")
                    else:
                        self.elevation_label.configure(foreground="green")
                
            # Update direction indicator
            self._draw_direction_indicator(dx, dy, dz)
            
            # Update signal strength (inverse of distance)
            if distance <= 0:
                self.signal_var.set(0.0)
                self.signal_bar.configure(style='Red.Horizontal.TProgressbar')
            else:
                # Normalize signal strength: stronger when closer
                # Maximum strength at 1m, diminishes with distance
                strength = min(1.0, 1.0 / max(1.0, distance))
                self.signal_var.set(strength)
                
                # Update signal bar color based on strength
                if strength > 0.85:
                    self.signal_bar.configure(style='Green.Horizontal.TProgressbar')
                elif strength > 0.5:
                    self.signal_bar.configure(style='Yellow.Horizontal.TProgressbar')
                elif strength > 0.25:
                    self.signal_bar.configure(style='Orange.Horizontal.TProgressbar')
                else:
                    self.signal_bar.configure(style='Red.Horizontal.TProgressbar')
                
            # Color-code the distance label based on proximity
            if distance <= 0:
                self.distance_label.configure(foreground="gray")
            elif distance < 5.0:
                self.distance_label.configure(foreground="green")
            elif distance < 15.0:
                self.distance_label.configure(foreground="orange")
            else:
                self.distance_label.configure(foreground="red")
                
        # Schedule UI update on the main thread
        self.root.after(0, update_ui)
        
    def _draw_direction_indicator(self, dx, dy, dz):
        """Draw a futuristic aeronautical direction indicator on the canvas showing victim direction"""
        # Clear canvas
        self.direction_canvas.delete("all")
        canvas_width = self.direction_canvas.winfo_width()
        canvas_height = self.direction_canvas.winfo_height()
        
        # Ensure we have minimum dimensions
        if canvas_width < 20 or canvas_height < 20:
            canvas_width = canvas_height = 250  # Increased from 150 to 250
            
        # Calculate center and radius
        center_x = canvas_width / 2
        center_y = canvas_height / 2
        radius = min(center_x, center_y) - 15  # Slightly larger margin (10 to 15)
        radius_int = int(radius)
        
        # Draw outer circle with gradient
        for i in range(3):
            opacity = 0.1 + i * 0.1
            color = f'#{int(0x00 * opacity):02x}{int(0xFF * opacity):02x}{int(0x00 * opacity):02x}'
        self.direction_canvas.create_oval(
            center_x - radius, center_y - radius, 
            center_x + radius, center_y + radius, 
                outline=color,
                width=3  # Thicker line (2 to 3)
        )
        
        # Draw inner circle
        inner_radius = radius * 0.8
        self.direction_canvas.create_oval(
            center_x - inner_radius, center_y - inner_radius,
            center_x + inner_radius, center_y + inner_radius,
            outline="#00FF00",
            width=2  # Thicker line (1 to 2)
        )
        
        # Add a simple crosshair in the center
        crosshair_size = radius * 0.2  # Size of the crosshair lines
        # Horizontal line
        self.direction_canvas.create_line(
            center_x - crosshair_size, center_y,
            center_x + crosshair_size, center_y,
            fill="#00FF00",
            width=2
        )
        # Vertical line
        self.direction_canvas.create_line(
            center_x, center_y - crosshair_size,
            center_x, center_y + crosshair_size,
            fill="#00FF00",
            width=2
        )
        
        # Draw distance rings with gradient
        for r in range(radius_int, 0, -radius_int//4):
            opacity = 0.2 + (1 - r/radius) * 0.3
            color = f'#{int(0x00 * opacity):02x}{int(0xFF * opacity):02x}{int(0x00 * opacity):02x}'
            self.direction_canvas.create_oval(
                center_x - r, center_y - r,
                center_x + r, center_y + r,
                outline=color,
                width=2  # Thicker line (1 to 2)
        )
        
        # If direction is valid, draw victim indicator
        if dx is not None and dy is not None and (dx != 0 or dy != 0):
            # Calculate endpoint of direction vector
            end_x = center_x + dx * radius
            end_y = center_y - dy * radius  # Inverted y-axis
            
            # Draw direction vector with HUD-style arrow
            # Main line
            self.direction_canvas.create_line(
                center_x, center_y,
                end_x, end_y,
                fill="#00FF00",
                width=3  # Thicker line (2 to 3)
            )
            
            # Draw arrow head
            arrow_size = 15  # Increased from 10 to 15
            angle = math.atan2(end_y - center_y, end_x - center_x)
            arrow_angle1 = angle + math.radians(150)
            arrow_angle2 = angle - math.radians(150)
            
            arrow_x1 = end_x + arrow_size * math.cos(arrow_angle1)
            arrow_y1 = end_y + arrow_size * math.sin(arrow_angle1)
            arrow_x2 = end_x + arrow_size * math.cos(arrow_angle2)
            arrow_y2 = end_y + arrow_size * math.sin(arrow_angle2)
            
            self.direction_canvas.create_polygon(
                end_x, end_y,
                arrow_x1, arrow_y1,
                arrow_x2, arrow_y2,
                fill="#00FF00",
                outline=""
            )
            
            # Draw victim point with HUD-style targeting reticle
            reticle_size = 22  # Increased from 15 to 22
            # Outer circle
            self.direction_canvas.create_oval(
                end_x - reticle_size, end_y - reticle_size,
                end_x + reticle_size, end_y + reticle_size,
                outline="#00FF00",
                width=2  # Thicker line (1 to 2)
            )
            # Inner circle
            self.direction_canvas.create_oval(
                end_x - reticle_size/2, end_y - reticle_size/2,
                end_x + reticle_size/2, end_y + reticle_size/2,
                outline="#00FF00",
                width=2  # Thicker line (1 to 2)
            )
            
            # Draw crosshair lines
            self.direction_canvas.create_line(
                end_x - reticle_size, end_y,
                end_x + reticle_size, end_y,
                fill="#00FF00",
                width=2  # Thicker line (1 to 2)
            )
            self.direction_canvas.create_line(
                end_x, end_y - reticle_size,
                end_x, end_y + reticle_size,
                fill="#00FF00",
                width=2  # Thicker line (1 to 2)
            )
        else:
            # If no vector, draw "not detected" text with HUD style
            self.direction_canvas.create_text(
                center_x, center_y,
                text="NO SIGNAL",
                fill="#00FF00",
                font=("Courier", 16, "bold")  # Larger font (12 to 16)
            )

    def _build_status_tab(self, parent):
        """Build the status tab with victim distance indicator"""
        # Title
        ttk.Label(parent, text="Simulation Status", style="Title.TLabel").pack(pady=(0,20))
        
        # UI Control status indicator (simplified)
        self.control_status_label = ttk.Label(
            parent,
            textvariable=self.control_status_var,
            foreground="#00FF00",  # Green text for visibility
            font=("Segoe UI", 10, "bold"),
            wraplength=400
        )
        self.control_status_label.pack(pady=5)
        
        # Victim indicator section
        victim_frame = ttk.LabelFrame(parent, text="Victim Detection", padding=15, labelanchor="n")
        victim_frame.pack(fill="x", pady=10)
        
        # Distance indicator
        ttk.Label(victim_frame, text="Distance to victim:", style="Subtitle.TLabel").pack(pady=5)
        self.distance_var = tk.StringVar(value="Not detected")
        self.distance_label = ttk.Label(victim_frame, textvariable=self.distance_var, 
                                      font=("Segoe UI", 14))
        self.distance_label.pack(pady=5)
        
        # Elevation indicator
        ttk.Label(victim_frame, text="Elevation difference:", style="Subtitle.TLabel").pack(pady=5)
        self.elevation_var = tk.StringVar(value="Not detected")
        self.elevation_label = ttk.Label(victim_frame, textvariable=self.elevation_var, 
                                       font=("Segoe UI", 14))
        self.elevation_label.pack(pady=5)
            
        # Direction indicator (graphical)
        ttk.Label(victim_frame, text="Direction:", style="Subtitle.TLabel").pack(pady=5)
        canvas_size = 250  # Increased from 150 to 250
        self.direction_canvas = tk.Canvas(victim_frame, width=canvas_size, height=canvas_size, 
                                         bg="black", highlightthickness=1, highlightbackground="#666666")
        self.direction_canvas.pack(pady=10)
        
        # Draw the initial state (no detection)
        self._draw_direction_indicator(None, None, None)
        
        # Signal strength (distance-based)
        ttk.Label(victim_frame, text="Signal strength:", style="Subtitle.TLabel").pack(pady=5)
        self.signal_var = tk.DoubleVar(value=0.0)
        self.signal_bar = ttk.Progressbar(victim_frame, variable=self.signal_var, maximum=1.0)
        self.signal_bar.pack(fill="x", pady=5, padx=10)

    def _build_help_tab(self, parent):
        """Build the help tab with application information and controls"""
        # Create a ScrollFrame for the help content
        scroll_frame = ScrollFrame(parent, bg="#0a0a0a")
        scroll_frame.pack(fill="both", expand=True)
        
        # Get the scrollable frame to add content to
        scrollable_frame = scroll_frame.scrollable_frame
        
        # Define enhanced styles for the help tab
        help_title_font = ("Segoe UI", 22, "bold")  # Larger title font
        section_title_font = ("Segoe UI", 14, "bold")  # Enhanced section title font
        help_content_font = ("Segoe UI", 12)  # Larger content font
        
        # Title with enhanced styling
        title_frame = ttk.Frame(scrollable_frame, padding=(0, 0, 0, 10))
        title_frame.pack(fill="x", pady=(0, 25))
        title_label = ttk.Label(
            title_frame, 
            text="Help & Information", 
            font=help_title_font,
            foreground="#00b4d8"  # Accent color for title
        )
        title_label.pack(pady=(5, 0))
        
        # Version Information Section with enhanced styling
        version_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Version Information", 
            padding=20,
            labelanchor="n"  # Center the label
        )
        version_frame.pack(fill="x", pady=10, padx=15)  # Increased padding
        
        version_info = """
• Version: HyperDrive Pathway v1.4.0B
• Build: 21.05.2025
        """
        version_label = ttk.Label(
            version_frame, 
            text=version_info, 
            justify="left",
            font=help_content_font
        )
        version_label.pack(fill="x")
        
        # Scene Tab Section
        scene_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Scene Tab", 
            padding=20,
            labelanchor="n"
        )
        scene_frame.pack(fill="x", pady=10, padx=15)
        
        scene_info = """
• Scene Creation Controls:
  - Create Environment: Generates a new disaster simulation environment with all configured objects
  - Clear Environment: Removes all objects from the current scene
  - Cancel Creating Environment: Stops the environment creation process if in progress
  - Progress bar shows creation status with category and element counts

• Scene Configuration:
  - Scene settings are controlled in the Config tab
  - Dynamic objects like birds and falling trees can be adjusted during runtime
        """
        scene_label = ttk.Label(
            scene_frame, 
            text=scene_info, 
            justify="left",
            font=help_content_font
        )
        scene_label.pack(fill="x")
        
        # Controls Tab Section
        controls_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Controls Tab", 
            padding=20,
            labelanchor="n"
        )
        controls_frame.pack(fill="x", pady=10, padx=15)
        
        controls_info = """
• Movement Mode:
  - Single-Axis Movement: Toggle between multi-directional and single-axis movement
  - When enabled, restricts movement to one axis at a time
  - Only the axis with the largest input will be active, all others will be disabled
  - For example, if you use pitch control, all other controls will be disabled until you release it

• Keyboard Controls:
  - Movement Speed: Adjust how quickly the drone moves with keyboard input
  - Rotation Speed: Adjust how quickly the drone rotates with keyboard input
  - Apply Keyboard Settings: Save changes to keyboard control settings

• RC Controller Settings:
  - Sensitivity: Adjust overall controller sensitivity (range 0.1-20.0)
  - Deadzone: Set minimum input threshold to prevent drift
  - Yaw Sensitivity: Set specific sensitivity for rotation control
  - Axis Mapping: Configure which joystick axes control which movements
  - Invert Controls: Toggle direction inversion for each axis
  - Test Controls: View real-time input values from the controller with visual joystick representation
  - RC Mapping Wizard: Visual interface for mapping controller axes with real-time feedback
        """
        controls_label = ttk.Label(
            controls_frame, 
            text=controls_info, 
            justify="left",
            font=help_content_font
        )
        controls_label.pack(fill="x")
        
        # Config Tab Section
        config_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Config Tab", 
            padding=20,
            labelanchor="n"
        )
        config_frame.pack(fill="x", pady=10, padx=15)
        
        config_info = """
• Dynamic Objects:
  - Number of Birds: Controls how many birds appear in the scene
  - Bird Movement Speed: Sets how fast birds fly (0.1-5.0)
  - Number of Falling Trees: Sets how many trees will randomly fall
  - Tree Spawn Interval: Time between tree spawns (in seconds)
  - Keep Fallen Trees: Select whether trees remain on ground after falling or are removed
  - Note: Birds and falling trees are managed separately

• Environment Settings:
  - Number of Static Trees: Sets the number of non-falling trees
  - Number of Rocks: Controls how many rock formations appear
  - Number of Bushes: Sets the amount of bush clusters
  - Number of Foliage: Controls ground vegetation density
  - Area Size: Sets the overall simulation area dimensions

• Simulation Settings:
  - Victim Count: Number of victims to place in the scene
  - Drone Speed: Maximum velocity of the drone
  - Move Step: Distance increment per movement command
  - Rotate Step: Angle increment per rotation command
  - Enable Collisions: Toggle collision detection
  - Enable Physics: Toggle physics simulation
  - Apply Changes: Save all configuration changes

• Save/Load Settings:
  - Save Settings: Save your current configuration to a file with custom name and location
                   (Default location is Config folder, same as rc_mapping.json and rc_settings.json)
  - Load Settings: Load previously saved configurations
        """
        config_label = ttk.Label(
            config_frame, 
            text=config_info, 
            justify="left",
            font=help_content_font
        )
        config_label.pack(fill="x")
        
        # Status Tab Section
        status_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Status Tab", 
            padding=20,
            labelanchor="n"
        )
        status_frame.pack(fill="x", pady=10, padx=15)
        
        status_info = """
• Control Status: Shows whether keyboard controls are active
  - Green: UI control active and ready for keyboard input
  - Red: UI control inactive (click window to activate)

• Victim Detection:
  - Distance: Shows how far the victim is from the drone
  - Elevation: Indicates height difference between drone and victim
  - Direction: Visual indicator showing victim's location
  - Signal Strength: Bar showing signal quality:
    > Green: Strong signal (close proximity)
    > Yellow: Moderate signal
    > Orange: Weak signal
    > Red: Very weak signal (far distance)

• HUD-style radar display shows victim location relative to drone
        """
        status_label = ttk.Label(
            status_frame, 
            text=status_info, 
            justify="left",
            font=help_content_font
        )
        status_label.pack(fill="x")
        
        # Monitor Tab Section
        monitor_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Monitor Tab", 
            padding=20,
            labelanchor="n"
        )
        monitor_frame.pack(fill="x", pady=10, padx=15)
        
        monitor_info = """
• Performance Monitoring Toggle:
  - Enable/disable real-time performance tracking
  - When disabled, conserves CPU resources

• System Information:
  - OS Version: Shows operating system version
  - Python Version: Shows Python interpreter version
  - CPU Cores: Number of processor cores available

• Performance Metrics:
  - FPS: Frames per second of the application
  - Memory Usage: Application memory consumption in MB
  - Memory %: Percentage of system memory in use
  - CPU Usage: Processor utilization percentage
  - CPU Frequency: Current processor clock speed
  - Active Threads: Number of running threads

• Simulation Statistics:
  - Total Objects: Count of all objects in the scene
  - Individual counts for birds, trees, rocks, bushes, and foliage

• Runtime Statistics:
  - Uptime: Duration the application has been running
        """
        monitor_label = ttk.Label(
            monitor_frame, 
            text=monitor_info, 
            justify="left",
            font=help_content_font
        )
        monitor_label.pack(fill="x")

        # Dataset Tab Section
        dataset_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Dataset Tab", 
            padding=20,
            labelanchor="n"
        )
        dataset_frame.pack(fill="x", pady=10, padx=15)
        
        dataset_info = """
• Dataset Directory:
  - View current dataset storage location
  - Select Directory: Change the directory where captures are saved
  - Uses timestamped subfolders for organization

• Batch Information:
  - Current Batch: Displays the latest batch number that was created
  - Scene Batch: Shows the batch number when the current scene was created
  - Refresh Batch Information: Updates the displayed batch numbers
  - Remove Batches From Current Scene: Deletes all batches created after the scene batch number

• Dataset Collection:
  - Automatically captures depth images during simulation
  - Organizes data into train/val/test splits
  - Stores depth maps, poses, and victim direction vectors
  - Includes distance-to-victim measurements

• Tools:
  - Open Depth Image Viewer: Launch a tool to examine and manipulate captured depth images
        """
        dataset_label = ttk.Label(
            dataset_frame, 
            text=dataset_info, 
            justify="left",
            font=help_content_font
        )
        dataset_label.pack(fill="x")

        # Logging Tab Section
        logging_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Logging Tab", 
            padding=20,
            labelanchor="n"
        )
        logging_frame.pack(fill="x", pady=10, padx=15)
        
        logging_info = """
• Log Level:
  - DEBUG: Shows all messages including detailed debugging
  - INFO: Shows information, warnings, and errors
  - WARNING: Shows only warnings and errors
  - ERROR: Shows only errors
  - CRITICAL: Shows only critical errors

• Debug Verbosity:
  - L1 (Basic): High-level information and important events
  - L2 (Medium): Detailed operations and parameters
  - L3 (Verbose): All events including frequent updates

• File Logging:
  - Enable/disable logging to file
  - Open logs directory to view saved logs
  - Logs are stored with timestamps for reference

• Verbose Mode:
  - Enable for maximum detail in debugging
  - Affects console output and file logging
        """
        logging_label = ttk.Label(
            logging_frame, 
            text=logging_info, 
            justify="left",
            font=help_content_font
        )
        logging_label.pack(fill="x")
        
        # Keyboard Controls Section
        keyboard_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Keyboard Controls", 
            padding=20,
            labelanchor="n"
        )
        keyboard_frame.pack(fill="x", pady=10, padx=15)
        
        keyboard_info = """
• Movement Controls:
  - W: Move forward
  - S: Move backward
  - A: Move left
  - D: Move right
  - Space: Move up
  - Z: Move down
  - Q: Rotate counterclockwise
  - E: Rotate clockwise

• Movement Modes:
  - Multi-directional: Default mode allowing movement in multiple directions at once
  - Single-axis: Restricts movement to one axis at a time:
    * Only the axis with the largest input will be active
    * All other axes will be disabled until you release the active axis
    * This creates clean, isolated movements for dataset collection
        """
        keyboard_label = ttk.Label(
            keyboard_frame, 
            text=keyboard_info, 
            justify="left",
            font=help_content_font
        )
        keyboard_label.pack(fill="x")
        
        # RC Joystick Controls section
        joystick_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="RC Joystick Controls", 
            padding=20,
            labelanchor="n"
        )
        joystick_frame.pack(fill="x", pady=10, padx=15)
        
        joystick_info = """
• Controller Setup:
  - Connect your joystick to the computer before starting the application
  - Select RC Controller at startup when prompted
  - Configure mappings in the Controls tab if needed

• Default Mappings:
  - Left stick X: Yaw (rotation)
  - Left stick Y: Throttle (up/down movement)
  - Right stick X: Roll (left/right movement)
  - Right stick Y: Pitch (forward/backward movement)

• Sensitivity Settings:
  - Main sensitivity (0.1-20.0): Adjusts overall responsiveness
  - Deadzone: Prevents drift when sticks are near center
  - Yaw sensitivity: Specifically adjusts rotation speed

• Visual Feedback:
  - Test window shows real-time joystick position with visual representations
  - Pitch/Roll visualizer shows forward/backward and left/right movement
  - Throttle/Yaw visualizer shows up/down movement and rotation
  - Progress bars show raw axis values for all detected joystick axes
        """
        joystick_label = ttk.Label(
            joystick_frame, 
            text=joystick_info, 
            justify="left",
            font=help_content_font
        )
        joystick_label.pack(fill="x")
        
        # Keyboard Shortcuts Section
        shortcuts_frame = ttk.LabelFrame(
            scrollable_frame, 
            text="Keyboard Shortcuts", 
            padding=20,
            labelanchor="n"
        )
        shortcuts_frame.pack(fill="x", pady=(10, 20), padx=15)
        
        shortcuts_info = """
• General Shortcuts:
  - Enter: Apply changes in configuration fields
  - Ctrl+S: Save current configuration
  - Ctrl+O: Load saved configuration
  - Esc: Cancel ongoing operations

• Tab Navigation:
  - Click tabs to switch between different sections
  - Some tabs provide real-time updates when selected
        """
        shortcuts_label = ttk.Label(
            shortcuts_frame, 
            text=shortcuts_info, 
            justify="left",
            font=help_content_font
        )
        shortcuts_label.pack(fill="x")
        
        # Note: Scrolling is now handled by the ScrollFrame class
        # No need for manual scroll event bindings

    def _save_config(self):
        """Save current configuration to a JSON file"""
        try:
            # First make sure we have the latest settings from the UI
            self._apply_all_config_changes()
            
            # Start with our complete current configuration
            config_to_save = dict(self.config)
            
            # Update with any UI values not yet applied
            for key, var in self._config_vars.items():
                if isinstance(var, tk.BooleanVar):
                    config_to_save[key] = var.get()
                else:
                    try:
                        # Try to convert to float if possible
                        config_to_save[key] = float(var.get())
                    except ValueError:
                        # Otherwise keep as string
                        config_to_save[key] = var.get()
            
            # Ensure move_step is not zero if it was previously non-zero
            if "move_step" in config_to_save and config_to_save["move_step"] == 0.0 and "move_step" in self.config and self.config["move_step"] > 0:
                config_to_save["move_step"] = self.config["move_step"]
                self.logger.info("MenuSystem", f"Preserving non-zero move_step in saved config: {config_to_save['move_step']}")
            
            # Create a dialog to get the custom name and allow directory selection
            dialog = tk.Toplevel(self.root)
            dialog.title("Save Configuration")
            dialog.geometry("600x450")
            dialog.transient(self.root)
            dialog.grab_set()  # Modal
            
            # Set minimum size to match current size
            dialog.minsize(600, 500)
            
            # Center on parent
            dialog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
            dialog.geometry(f"+{x}+{y}")
            
            # Content
            content_frame = ttk.Frame(dialog, padding=35)
            content_frame.pack(fill=tk.BOTH, expand=True)
            
            # Description explaining the purpose
            ttk.Label(
                content_frame,
                text="Save your current configuration settings",
                font=("Segoe UI", 11, "bold"),
                wraplength=350,
                justify="center"
            ).pack(pady=(0, 10))
            
            # Add note about controls being included
            ttk.Label(
                content_frame,
                text="Note: All settings including control mappings will be saved.",
                font=("Segoe UI", 10, "italic"),
                wraplength=350,
                foreground="#666666",
                justify="center"
            ).pack(pady=(0, 10))
            
            # File name section
            ttk.Label(
                content_frame, 
                text="Enter a name for this configuration:",
                font=("Segoe UI", 12)
            ).pack(pady=(0, 10))
            
            # Entry for custom name
            name_var = tk.StringVar(value="settings")
            name_entry = ttk.Entry(content_frame, textvariable=name_var, width=30, font=("Segoe UI", 12))
            name_entry.pack(fill=tk.X, pady=10, ipady=5)
            name_entry.focus_set()  # Set focus to the entry
            
            # Directory section
            ttk.Label(
                content_frame, 
                text="Save location:",
                font=("Segoe UI", 12)
            ).pack(pady=(10, 5))
            
            # Default directory is Config folder
            default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Config")
            dir_var = tk.StringVar(value=default_dir)
            
            # Directory display and browse button in a frame
            dir_frame = ttk.Frame(content_frame)
            dir_frame.pack(fill=tk.X, pady=5)
            
            dir_entry = ttk.Entry(dir_frame, textvariable=dir_var, width=25, font=("Segoe UI", 10))
            dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            
            def browse_directory():
                directory = filedialog.askdirectory(
                    title="Select Save Directory",
                    initialdir=dir_var.get()
                )
                if directory:
                    dir_var.set(directory)
            
            browse_btn = ttk.Button(dir_frame, text="Browse", command=browse_directory)
            browse_btn.pack(side=tk.RIGHT)
            
            # Help text
            ttk.Label(
                content_frame,
                text="Default location is the Config folder, same as rc_mapping.json and rc_settings.json",
                font=("Segoe UI", 10),
                foreground="#666666",
                wraplength=350,
                justify="center"
            ).pack(pady=(5, 20))
            
            # Buttons
            button_frame = ttk.Frame(content_frame)
            button_frame.pack(fill=tk.X, pady=10)
            
            cancel_btn = ttk.Button(
                button_frame, 
                text="Cancel", 
                command=dialog.destroy
            )
            cancel_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X, ipady=4)
            
            def save_config_with_name():
                filename = name_var.get()
                directory = dir_var.get()
                
                # Make sure the filename is valid by removing special characters
                filename = ''.join(c for c in filename if c.isalnum() or c in '._- ')
                
                # Check if the name already has a .json extension
                if not filename.lower().endswith('.json'):
                    filename = f"{filename}.json"
                
                # Ensure directory exists
                os.makedirs(directory, exist_ok=True)
                
                # Full path to save file
                filepath = os.path.join(directory, filename)
                
                # Format the JSON with indentation for readability
                config_json = json.dumps(config_to_save, indent=4)
                
                # Save to file
                with open(filepath, "w") as f:
                    f.write(config_json)
                
                # Explicitly publish events to ensure movement settings are applied
                EM.publish('config/updated', 'move_step')
                EM.publish('config/updated', 'rotate_step_deg')
                
                self.logger.info("MenuSystem", f"Configuration saved to {filepath} with move_step={config_to_save.get('move_step', 0.0):.2f}")
                
                # Update status
                self.status_label.configure(text=f"Configuration saved to {os.path.basename(filepath)}")
                self.root.after(2000, lambda: self.status_label.configure(text=""))
                
                # Close dialog
                dialog.destroy()
            
            save_btn = ttk.Button(
                button_frame, 
                text="Save", 
                style="Apply.TButton",
                command=save_config_with_name
            )
            save_btn.pack(side=tk.RIGHT, padx=10, expand=True, fill=tk.X, ipady=4)
            
            # Bind Enter key to save button
            dialog.bind("<Return>", lambda event: save_btn.invoke())
            
            return True
        except Exception as e:
            self.logger.error("MenuSystem", f"Error saving configuration: {e}")
            self.status_label.configure(text=f"Error saving configuration: {e}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            return False

    def _load_config(self):
        """Load configuration from a JSON file"""
        try:
            # Get default Config directory path
            default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Config")
            
            # Open file dialog to choose file to load
            file_path = filedialog.askopenfilename(
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                title="Load Configuration",
                initialdir=default_dir
            )
            
            if file_path:
                # Read the configuration file
                with open(file_path, 'r') as f:
                    loaded_config = json.load(f)
                
                # Show confirmation dialog
                dialog = tk.Toplevel(self.root)
                dialog.title("Load Configuration")
                dialog.geometry("600x350")
                dialog.transient(self.root)
                dialog.grab_set()  # Modal
                
                # Center on parent
                dialog.update_idletasks()
                x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
                y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
                dialog.geometry(f"+{x}+{y}")
                
                # Content
                content_frame = ttk.Frame(dialog, padding=35)
                content_frame.pack(fill=tk.BOTH, expand=True)
                
                # Description
                ttk.Label(
                    content_frame,
                    text=f"Load configuration from:\n{os.path.basename(file_path)}",
                    font=("Segoe UI", 11, "bold"),
                    wraplength=350,
                    justify="center"
                ).pack(pady=(0, 20))
                
                # Add file path info
                ttk.Label(
                    content_frame,
                    text=f"Path: {file_path}",
                    font=("Segoe UI", 9),
                    wraplength=500,
                    foreground="#666666",
                    justify="center"
                ).pack(pady=(0, 10))
                
                # Add note about controls being included
                ttk.Label(
                    content_frame,
                    text="Note: This will replace ALL current settings including control mappings and keyboard/RC settings.",
                    font=("Segoe UI", 10),
                    wraplength=350,
                    foreground="#DD0000",
                    justify="center"
                ).pack(pady=(0, 20))
                
                # Buttons
                button_frame = ttk.Frame(content_frame)
                button_frame.pack(fill=tk.X, pady=20)
                
                cancel_btn = ttk.Button(
                    button_frame, 
                    text="Cancel", 
                    command=dialog.destroy
                )
                cancel_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X, ipady=4)
                
                load_btn = ttk.Button(
                    button_frame, 
                    text="Load Configuration", 
                    style="Apply.TButton",
                    command=lambda: self._confirm_load_config(dialog, loaded_config, file_path)
                )
                load_btn.pack(side=tk.RIGHT, padx=10, expand=True, fill=tk.X, ipady=4)
        except Exception as e:
            self.status_label.configure(text=f"Error loading configuration: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))

    def _confirm_load_config(self, dialog, loaded_config, file_path):
        """Apply the loaded configuration after confirmation"""
        dialog.destroy()  # Close original dialog
        
        try:
            # Create a new dialog to show settings that will be changed
            preview_dialog = tk.Toplevel(self.root)
            preview_dialog.title("Configuration Preview")
            preview_dialog.geometry("1000x400")  # Increased size for better readability
            preview_dialog.minsize(1000, 400)
            preview_dialog.configure(bg="#1a1a1a")  # Set dark background
            preview_dialog.transient(self.root)
            preview_dialog.grab_set()  # Modal
            
            # Center on parent
            preview_dialog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (preview_dialog.winfo_width() // 2)
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (preview_dialog.winfo_height() // 2)
            preview_dialog.geometry(f"+{x}+{y}")
            
            # Content
            frame = ttk.Frame(preview_dialog, padding=20, style="Dark.TFrame")
            frame.pack(fill=tk.BOTH, expand=True)
            
            # Title
            ttk.Label(
                frame,
                text=f"Preview of Settings from:\n{os.path.basename(file_path)}",
                font=("Segoe UI", 14, "bold"),
                foreground="#FFFFFF",  # Change text color to white
                wraplength=550,
                justify="center"
            ).pack(pady=(0, 10))
            
            # Categorize settings
            rc_settings = {}
            movement_settings = {}
            environment_settings = {}
            other_settings = {}
            
            # Check for RC controller settings
            rc_keys = ['rc_sensitivity', 'rc_deadzone', 'rc_yaw_sensitivity', 'single_axis_mode']
            
            # Track changed settings
            changed_settings = []
            
            for key, value in loaded_config.items():
                # Skip the flag
                if key == 'includes_rc_settings':
                    continue
                    
                # Check if value is different from current
                current_value = self.config.get(key, "Not set")
                if value != current_value:
                    changed_settings.append(key)
                
                # Categorize the setting
                if key in rc_keys or key == 'rc_mappings':
                    rc_settings[key] = value
                elif key in ['move_step', 'rotate_step_deg']:
                    movement_settings[key] = value
                elif key in ['num_trees', 'num_rocks', 'num_bushes', 'num_birds', 
                           'num_falling_trees', 'num_foliage', 'area_size', 'tree_spawn_interval', 'bird_speed']:
                    environment_settings[key] = value
                else:
                    other_settings[key] = value
            
            # Show number of changes
            changes_frame = ttk.Frame(frame, style="Dark.TFrame")
            changes_frame.pack(fill="x", pady=5)
            
            changes_count = len(changed_settings)
            changes_text = f"{changes_count} setting{'s' if changes_count != 1 else ''} will be changed"
            
            ttk.Label(
                changes_frame,
                text=changes_text,
                font=("Segoe UI", 11, "bold"),
                foreground="#FF6600" if changes_count > 0 else "#00AA00"
            ).pack(side="left", pady=5)
            
            # Add toggle for "Show changed settings only"
            show_changed_only = tk.BooleanVar(value=True)
            
            def refresh_settings_display():
                # Clear previous frames
                for widget in settings_frame.winfo_children():
                    widget.destroy()
                
                # Add sections with settings
                add_section("RC Controller Settings", rc_settings, self.config, show_changed_only.get())
                add_section("Movement Settings", movement_settings, self.config, show_changed_only.get())
                add_section("Environment Settings", environment_settings, self.config, show_changed_only.get())
                add_section("Other Settings", other_settings, self.config, show_changed_only.get())
            
            # Checkbox for show changed only
            show_changed_check = ttk.Checkbutton(
                changes_frame,
                text="Show changed settings only",
                variable=show_changed_only,
                command=refresh_settings_display
            )
            show_changed_check.pack(side="right", padx=10)
            
            # Create a canvas with scrollbar for the settings
            canvas = tk.Canvas(frame, highlightthickness=0, bg="#1a1a1a")
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
            settings_frame = ttk.Frame(canvas, style="Dark.TFrame")
            
            # Configure canvas
            canvas.configure(yscrollcommand=scrollbar.set, bg="#1a1a1a")
            canvas.create_window((0, 0), window=settings_frame, anchor="nw", width=590)  # Wider for better visibility
            settings_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            
            # Pack canvas and scrollbar
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # Function to add a section of settings
            def add_section(title, settings_dict, current_dict, changed_only=True):
                # Prepare data for display
                display_data = []
                for key, new_value in settings_dict.items():
                    current_value = current_dict.get(key, "Not set")
                    
                    # Skip unchanged settings if filter is enabled
                    if changed_only and new_value == current_value:
                        continue
                    
                    display_data.append((key, current_value, new_value))
                
                # Skip empty sections
                if not display_data:
                    return
                
                # Section title
                section_frame = ttk.LabelFrame(settings_frame, text=title, padding=10, style="Dark.TLabelframe")
                section_frame.pack(fill="x", pady=5, padx=5)
                
                # Table headers
                header_frame = ttk.Frame(section_frame, style="Dark.TFrame")
                header_frame.pack(fill="x", pady=5)
                
                ttk.Label(
                    header_frame,
                    text="Setting",
                    font=("Segoe UI", 10, "bold"),
                    foreground="#FFFFFF",  # Add white text color
                    width=25
                ).pack(side="left")
                
                ttk.Label(
                    header_frame,
                    text="Current Value",
                    font=("Segoe UI", 10, "bold"),
                    foreground="#FFFFFF",  # Add white text color
                    width=15
                ).pack(side="left")
                
                ttk.Label(
                    header_frame,
                    text="New Value",
                    font=("Segoe UI", 10, "bold"),
                    foreground="#FFFFFF",  # Add white text color
                    width=15
                ).pack(side="left")
                
                # Add separator
                ttk.Separator(section_frame, orient="horizontal").pack(fill="x", pady=5)
                
                # Mapping of raw settings to human-readable names
                setting_names = {
                    # RC Settings
                    "rc_sensitivity": "RC Sensitivity",
                    "rc_deadzone": "RC Deadzone",
                    "rc_yaw_sensitivity": "RC Yaw Sensitivity",
                    "rc_mappings": "RC Control Mappings",
                    "single_axis_mode": "Single-Axis Mode",
                    
                    # Movement Settings
                    "move_step": "Movement Speed",
                    "rotate_step_deg": "Rotation Speed",
                    
                    # Environment Settings
                    "num_trees": "Static Trees",
                    "num_rocks": "Rocks",
                    "num_bushes": "Bushes",
                    "num_foliage": "Foliage",
                    "num_birds": "Birds",
                    "tree_spawn_interval": "Tree Spawn Interval (s)",
                    "num_falling_trees": "Falling Trees",
                    "area_size": "Area Size",
                    "bird_speed": "Bird Speed"
                }
                
                # Add settings rows
                for key, current_value, new_value in display_data:
                    # Create row
                    row_frame = ttk.Frame(section_frame, style="Dark.TFrame")
                    row_frame.pack(fill="x", pady=2)
                    
                    # Setting name (use human-readable name if available)
                    display_name = setting_names.get(key, key)
                    
                    # Mark changed settings with a different color
                    name_color = "#0066CC" if current_value != new_value else "#FFFFFF"
                    
                    ttk.Label(
                        row_frame,
                        text=display_name,
                        foreground=name_color,
                        font=("Segoe UI", 10, "bold" if current_value != new_value else "normal"),
                        width=25
                    ).pack(side="left")
                    
                    # Format values based on their type
                    def format_value(value):
                        if value == "Not set":
                            return value
                        
                        # Format booleans
                        if isinstance(value, bool):
                            return "Enabled" if value else "Disabled"
                            
                        # Format RC mappings
                        if key == "rc_mappings" and isinstance(value, dict):
                            # Count mapped controls
                            mapped_count = sum(1 for control in ["throttle", "yaw", "pitch", "roll"] if control in value)
                            return f"{mapped_count}/4 controls mapped"
                        
                        # Format floats with appropriate precision
                        if isinstance(value, float):
                            if key == "rc_yaw_sensitivity":
                                return f"{int(value * 100)}%"  # Display as percentage
                            elif abs(value) < 0.1:
                                return f"{value:.3f}"  # More precision for very small values
                            elif abs(value) < 1:
                                return f"{value:.2f}"
                            else:
                                return f"{value:.1f}"
                                
                        # Default formatting
                        return str(value)
                    
                    # Current value
                    current_text = format_value(current_value)
                    if len(current_text) > 15:
                        current_text = current_text[:12] + "..."
                    
                    ttk.Label(
                        row_frame,
                        text=current_text,
                        foreground="#FFFFFF",  # Add white foreground color
                        width=15
                    ).pack(side="left")
                    
                    # New value
                    new_text = format_value(new_value)
                    if len(new_text) > 15:
                        new_text = new_text[:12] + "..."
                    
                    # Show changed values in green, use regular color for unchanged values
                    value_color = "#008800" if current_value != new_value else "#FFFFFF"
                    
                    ttk.Label(
                        row_frame,
                        text=new_text,
                        foreground=value_color,
                        font=("Segoe UI", 10, "bold" if current_value != new_value else "normal"),
                        width=15
                    ).pack(side="left")
                    
                    # For boolean values, add a visual indicator
                    if isinstance(new_value, bool):
                        indicator_color = "#00AA00" if new_value else "#AA0000"
                        indicator = "■" if new_value else "□"
                        ttk.Label(
                            row_frame,
                            text=indicator,
                            foreground=indicator_color,
                            font=("Segoe UI", 12, "bold")
                        ).pack(side="left", padx=5)
                    
                    # For rc_mappings, add a details button
                    if key == "rc_mappings" and isinstance(new_value, dict):
                        details_btn = ttk.Button(
                            row_frame,
                            text="Details",
                            width=8,
                            command=lambda m=new_value: self._show_mapping_details(preview_dialog, m)
                        )
                        details_btn.pack(side="left", padx=5)
            
            # Call refresh to populate the settings display
            refresh_settings_display()
            
            # Buttons
            button_frame = ttk.Frame(frame, style="Dark.TFrame")
            button_frame.pack(fill=tk.X, pady=20)
            
            cancel_btn = ttk.Button(
                button_frame, 
                text="Cancel", 
                command=preview_dialog.destroy
            )
            cancel_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X, ipady=4)
            
            apply_btn = ttk.Button(
                button_frame, 
                text="Apply These Settings", 
                style="Apply.TButton",
                command=lambda: self._apply_loaded_config(preview_dialog, loaded_config, file_path)
            )
            apply_btn.pack(side=tk.RIGHT, padx=10, expand=True, fill=tk.X, ipady=4)
        
        except Exception as e:
            self.logger.error("MenuSystem", f"Error showing config preview: {e}")
            self.status_label.configure(text=f"Error previewing configuration: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))
    
    def _apply_loaded_config(self, dialog, loaded_config, file_path):
        """Apply loaded configuration from file"""
        try:
            # Update our configuration with the loaded values
            self.config.update(loaded_config)
            
            # Update UI variables with loaded values
            for key, value in loaded_config.items():
                if key in self._config_vars:
                    self._config_vars[key].set(value)
            
            # Ensure move_step is not zero if it was previously non-zero
            if "move_step" in loaded_config and loaded_config["move_step"] == 0.0 and hasattr(self, "move_step_var"):
                # Check if we have a previous non-zero value
                previous_value = self.move_step_var.get()
                if previous_value > 0:
                    self.config["move_step"] = previous_value
                    self.move_step_var.set(previous_value)
                    self.logger.info("MenuSystem", f"Preserving non-zero move_step value: {previous_value}")
            
            # Explicitly publish events to ensure movement settings are applied
            EM.publish('config/updated', 'move_step')
            EM.publish('config/updated', 'rotate_step_deg')
            
            # Update status
            self.status_label.configure(text=f"Configuration loaded from {os.path.basename(file_path)}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            
            self.logger.info("MenuSystem", f"Configuration loaded with move_step={self.config.get('move_step', 0.0):.2f}")
            
            # Close the dialog
            dialog.destroy()
        except Exception as e:
            self.logger.error("MenuSystem", f"Error applying loaded configuration: {e}")
            self.status_label.configure(text=f"Error applying loaded configuration: {e}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            dialog.destroy()

    def _update_performance_metrics(self):
        """Update performance metrics in the UI"""
        try:
            if not hasattr(self, 'root') or not self.root:
                return

            # Calculate current FPS
            current_time = time.time()
            if self._frame_times:
                # Calculate FPS from the most recent frame times
                frame_count = min(len(self._frame_times), 60)  # Use up to 60 frames for calculation
                time_span = current_time - self._frame_times[-min(frame_count, len(self._frame_times))]
                if time_span > 0:
                    fps = frame_count / time_span
                    if hasattr(self, 'fps_var'):
                        self.fps_var.set(f"{fps:.1f} FPS")

            # Update uptime
            uptime = current_time - self._start_time
            hours = int(uptime // 3600)
            minutes = int((uptime % 3600) // 60)
            seconds = int(uptime % 60)
            if hasattr(self, 'uptime_var'):
                self.uptime_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

            # Update memory usage
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB
            if hasattr(self, 'mem_var'):
                self.mem_var.set(f"{memory_mb:.1f} MB")
                
            # Update memory percentage
            mem_percent = psutil.virtual_memory().percent
            if hasattr(self, 'mem_percent_var'):
                self.mem_percent_var.set(f"{mem_percent:.1f}%")

            # Get CPU usage (this is percentage of a single core)
            cpu_percent = psutil.cpu_percent(interval=None)
            if hasattr(self, 'cpu_usage_var'):
                self.cpu_usage_var.set(f"{cpu_percent:.1f}%")
                
            # Get CPU frequency
            try:
                cpu_freq = psutil.cpu_freq().current
                if hasattr(self, 'cpu_freq_var'):
                    self.cpu_freq_var.set(f"{cpu_freq:.0f} MHz")
            except Exception:
                if hasattr(self, 'cpu_freq_var'):
                    self.cpu_freq_var.set("N/A")
                    
            # Get thread count
            thread_count = threading.active_count()
            if hasattr(self, 'thread_var'):
                self.thread_var.set(str(thread_count))

            # Update simulation statistics
            self._update_simulation_stats()

            # Don't schedule here - scheduling is handled by _schedule_ui_update
        except Exception as e:
            self.logger.error("MenuSystem", f"Error updating performance metrics: {e}")

    def _update_simulation_stats(self):
        """Update simulation statistics based on current config"""
        try:
            # Get values from config
            num_birds = self.config.get("num_birds", 0)
            num_trees = self.config.get("num_trees", 0)
            num_rocks = self.config.get("num_rocks", 0)
            num_bushes = self.config.get("num_bushes", 0)
            num_foliage = self.config.get("num_foliage", 0)
            
            # Update individual counts
            self.birds_var.set(str(num_birds))
            self.trees_var.set(str(num_trees))
            self.rocks_var.set(str(num_rocks))
            self.bushes_var.set(str(num_bushes))
            self.foliage_var.set(str(num_foliage))
            
            # Update total count
            total_objects = num_birds + num_trees + num_rocks + num_bushes + num_foliage
            self.obj_var.set(str(total_objects))
        except Exception:
            self.obj_var.set("N/A")
            self.birds_var.set("N/A")
            self.trees_var.set("N/A")
            self.rocks_var.set("N/A")
            self.bushes_var.set("N/A")
            self.foliage_var.set("N/A")

    def _build_performance_tab(self, parent):
        """Build the performance monitoring tab"""
        # Title
        ttk.Label(parent, text="Performance Monitoring", style="Title.TLabel").pack(pady=(0,20))
        
        # Monitoring Toggle
        toggle_frame = ttk.Frame(parent)
        toggle_frame.pack(fill="x", pady=(0, 10))
        
        # Create the toggle button
        self.monitoring_var = tk.BooleanVar(value=self.config.get("enable_performance_monitoring", False))
        toggle_btn = ttk.Checkbutton(toggle_frame, 
                                   text="Enable Performance Monitoring",
                                   variable=self.monitoring_var,
                                   command=self._toggle_monitoring)
        toggle_btn.pack(side="left", padx=5)
        
        # Create a simple frame instead of scrollable canvas
        scrollable_frame = ttk.Frame(parent)
        scrollable_frame.pack(fill="both", expand=True, padx=5)
        
        # System Information Section
        sys_frame = ttk.LabelFrame(scrollable_frame, text="System Information", padding=15, labelanchor="n")
        sys_frame.pack(fill="x", pady=10, padx=5)
        
        # OS Info
        os_frame = ttk.Frame(sys_frame)
        os_frame.pack(fill="x", pady=2)
        ttk.Label(os_frame, text="Operating System:", width=25, style="TLabel").pack(side="left")
        self.os_var = tk.StringVar(value=platform.system() + " " + platform.release())
        ttk.Label(os_frame, textvariable=self.os_var, style="TLabel").pack(side="left")
        
        # Python Version
        py_frame = ttk.Frame(sys_frame)
        py_frame.pack(fill="x", pady=2)
        ttk.Label(py_frame, text="Python Version:", width=25, style="TLabel").pack(side="left")
        self.py_var = tk.StringVar(value=platform.python_version())
        ttk.Label(py_frame, textvariable=self.py_var, style="TLabel").pack(side="left")
        
        # CPU Info
        cpu_info_frame = ttk.Frame(sys_frame)
        cpu_info_frame.pack(fill="x", pady=2)
        ttk.Label(cpu_info_frame, text="CPU Cores:", width=25, style="TLabel").pack(side="left")
        self.cpu_cores_var = tk.StringVar(value=str(psutil.cpu_count()))
        ttk.Label(cpu_info_frame, textvariable=self.cpu_cores_var, style="TLabel").pack(side="left")
        
        # Performance Metrics Section
        perf_frame = ttk.LabelFrame(scrollable_frame, text="Performance Metrics", padding=15, labelanchor="n")
        perf_frame.pack(fill="x", pady=10, padx=5)
        
        # FPS counter
        fps_frame = ttk.Frame(perf_frame)
        fps_frame.pack(fill="x", pady=2)
        ttk.Label(fps_frame, text="FPS:", width=25, style="TLabel").pack(side="left")
        self.fps_var = tk.StringVar(value="0.0")
        ttk.Label(fps_frame, textvariable=self.fps_var, style="TLabel").pack(side="left")
        
        # Memory usage
        mem_frame = ttk.Frame(perf_frame)
        mem_frame.pack(fill="x", pady=2)
        ttk.Label(mem_frame, text="Memory Usage:", width=25, style="TLabel").pack(side="left")
        self.mem_var = tk.StringVar(value="0 MB")
        ttk.Label(mem_frame, textvariable=self.mem_var, style="TLabel").pack(side="left")
        
        # Memory percentage
        mem_percent_frame = ttk.Frame(perf_frame)
        mem_percent_frame.pack(fill="x", pady=2)
        ttk.Label(mem_percent_frame, text="Memory %:", width=25, style="TLabel").pack(side="left")
        self.mem_percent_var = tk.StringVar(value="0%")
        ttk.Label(mem_percent_frame, textvariable=self.mem_percent_var, style="TLabel").pack(side="left")
        
        # CPU usage
        cpu_frame = ttk.Frame(perf_frame)
        cpu_frame.pack(fill="x", pady=2)
        ttk.Label(cpu_frame, text="CPU Usage:", width=25, style="TLabel").pack(side="left")
        self.cpu_usage_var = tk.StringVar(value="0%")
        ttk.Label(cpu_frame, textvariable=self.cpu_usage_var, style="TLabel").pack(side="left")
        
        # CPU frequency
        cpu_freq_frame = ttk.Frame(perf_frame)
        cpu_freq_frame.pack(fill="x", pady=2)
        ttk.Label(cpu_freq_frame, text="CPU Frequency:", width=25, style="TLabel").pack(side="left")
        self.cpu_freq_var = tk.StringVar(value="N/A")
        ttk.Label(cpu_freq_frame, textvariable=self.cpu_freq_var, style="TLabel").pack(side="left")
        
        # Thread count
        thread_frame = ttk.Frame(perf_frame)
        thread_frame.pack(fill="x", pady=2)
        ttk.Label(thread_frame, text="Active Threads:", width=25, style="TLabel").pack(side="left")
        self.thread_var = tk.StringVar(value="0")
        ttk.Label(thread_frame, textvariable=self.thread_var, style="TLabel").pack(side="left")
        
        # Simulation Statistics Section
        sim_frame = ttk.LabelFrame(scrollable_frame, text="Simulation Statistics", padding=15, labelanchor="n")
        sim_frame.pack(fill="x", pady=10, padx=5)
        
        # Scene objects
        obj_frame = ttk.Frame(sim_frame)
        obj_frame.pack(fill="x", pady=2)
        ttk.Label(obj_frame, text="Total Objects:", width=25, style="TLabel").pack(side="left")
        self.obj_var = tk.StringVar(value="0")
        ttk.Label(obj_frame, textvariable=self.obj_var, style="TLabel").pack(side="left")
        
        # Birds count
        birds_frame = ttk.Frame(sim_frame)
        birds_frame.pack(fill="x", pady=2)
        ttk.Label(birds_frame, text="Birds:", width=25, style="TLabel").pack(side="left")
        self.birds_var = tk.StringVar(value="0")
        ttk.Label(birds_frame, textvariable=self.birds_var, style="TLabel").pack(side="left")
        
        # Trees count
        trees_frame = ttk.Frame(sim_frame)
        trees_frame.pack(fill="x", pady=2)
        ttk.Label(trees_frame, text="Trees:", width=25, style="TLabel").pack(side="left")
        self.trees_var = tk.StringVar(value="0")
        ttk.Label(trees_frame, textvariable=self.trees_var, style="TLabel").pack(side="left")
        
        # Rocks count
        rocks_frame = ttk.Frame(sim_frame)
        rocks_frame.pack(fill="x", pady=2)
        ttk.Label(rocks_frame, text="Rocks:", width=25, style="TLabel").pack(side="left")
        self.rocks_var = tk.StringVar(value="0")
        ttk.Label(rocks_frame, textvariable=self.rocks_var, style="TLabel").pack(side="left")
        
        # Bushes count
        bushes_frame = ttk.Frame(sim_frame)
        bushes_frame.pack(fill="x", pady=2)
        ttk.Label(bushes_frame, text="Bushes:", width=25, style="TLabel").pack(side="left")
        self.bushes_var = tk.StringVar(value="0")
        ttk.Label(bushes_frame, textvariable=self.bushes_var, style="TLabel").pack(side="left")
        
        # Foliage count
        foliage_frame = ttk.Frame(sim_frame)
        foliage_frame.pack(fill="x", pady=2)
        ttk.Label(foliage_frame, text="Foliage:", width=25, style="TLabel").pack(side="left")
        self.foliage_var = tk.StringVar(value="0")
        ttk.Label(foliage_frame, textvariable=self.foliage_var, style="TLabel").pack(side="left")
        
        # Runtime Statistics Section
        runtime_frame = ttk.LabelFrame(scrollable_frame, text="Runtime Statistics", padding=15, labelanchor="n")
        runtime_frame.pack(fill="x", pady=10, padx=5)
        
        # Uptime
        uptime_frame = ttk.Frame(runtime_frame)
        uptime_frame.pack(fill="x", pady=2)
        ttk.Label(uptime_frame, text="Uptime:", width=25, style="TLabel").pack(side="left")
        self.uptime_var = tk.StringVar(value="00:00:00")
        ttk.Label(uptime_frame, textvariable=self.uptime_var, style="TLabel").pack(side="left")
        
        # Start performance monitoring
        self._schedule_ui_update()

    def _clear_performance_metrics(self):
        """Clear all performance metrics when monitoring is disabled"""
        self.fps_var.set("N/A")
        self.mem_var.set("N/A")
        self.mem_percent_var.set("N/A")
        self.cpu_usage_var.set("N/A")
        self.cpu_freq_var.set("N/A")
        self.thread_var.set("N/A")
        self._frame_times = []

    def _toggle_monitoring(self):
        """Handle monitoring toggle button click"""
        is_enabled = self.monitoring_var.get()
        self.config["enable_performance_monitoring"] = is_enabled
        
        if is_enabled:
            self._schedule_ui_update()
        else:
            if self._monitoring_after_id:
                self.root.after_cancel(self._monitoring_after_id)
                self._monitoring_after_id = None
            self._monitoring_active = False
            self._clear_performance_metrics()
            self._last_ui_update = 0
            self._last_fps_update = 0

    def run(self):
        """Run the UI main loop"""
        self.logger.info("MenuSystem", "Starting UI main loop")
        self.root.mainloop()
        
    def cleanup(self, data=None):
        """Perform cleanup before application exit"""
        # Perform cleanup tasks
        self.logger.info("MenuSystem", "Performing cleanup tasks...")
        
        # Cancel any pending scheduled tasks
        if hasattr(self, '_monitoring_after_id') and self._monitoring_after_id:
            try:
                self.root.after_cancel(self._monitoring_after_id)
                self._monitoring_after_id = None
            except Exception as e:
                self.logger.error("MenuSystem", f"Error cleaning up monitoring after task: {e}")
        
        # Cancel movement update schedule
        try:
            # Get all "after" ids and cancel them
            for after_id in self.root.tk.call('after', 'info'):
                try:
                    self.root.after_cancel(after_id)
                except Exception as e:
                    self.logger.debug("MenuSystem", f"Error canceling after task {after_id}: {e}")
        except Exception as e:
            self.logger.error("MenuSystem", f"Error cleaning up after tasks: {e}")
        
        # Clear any pressed keys and stop movement
        self._ui_pressed_keys.clear()
        try:
            # Explicitly stop all movement by publishing zero values
            EM.publish('keyboard/move', (0.0, 0.0, 0.0, 8))
            EM.publish('keyboard/rotate', (0.0, 8))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error stopping movement: {e}")
        
        # Clean up RC settings if they exist
        if hasattr(self, 'rc_settings') and self.rc_settings:
            try:
                self.rc_settings.destroy()
            except Exception as e:
                self.logger.error("MenuSystem", f"Error cleaning up RC settings: {e}")
        
        # Unsubscribe from events
        EM.unsubscribe('scene/progress', self._on_scene_progress)
        EM.unsubscribe('scene/completed', self._on_scene_completed)
        EM.unsubscribe('scene/canceled', self._on_scene_canceled)
        EM.unsubscribe('scene/request_creation', self._on_scene_creation_request)
        EM.unsubscribe('victim/detected', self._update_victim_indicator)
        EM.unsubscribe('simulation/frame', self._on_simulation_frame)
        EM.unsubscribe('config/updated', self._on_config_updated_gui)
        EM.unsubscribe('dataset/batch_saved', self._on_batch_saved)
        EM.unsubscribe('dataset/config_updated', self._on_dataset_config_updated)
        EM.unsubscribe('dataset/status_update', self._force_ui_update)
        
        self.logger.info("MenuSystem", "Cleanup complete - all events unsubscribed")

    def _build_dataset_tab(self, parent):
        """Build the dataset tab for configuring dataset collection"""
        # Title with modern styling
        title_frame = ttk.Frame(parent)
        title_frame.pack(fill="x", pady=(0, 20))
        ttk.Label(title_frame, text="Dataset Configuration", style="Title.TLabel").pack()
        
        # Directory Selection Section
        dir_frame = ttk.LabelFrame(parent, text="Dataset Directory", padding=15, labelanchor="n")
        dir_frame.pack(fill="x", pady=10, padx=5)
        
        # Current Directory Display
        current_dir_frame = ttk.Frame(dir_frame)
        current_dir_frame.pack(fill="x", pady=5)
        ttk.Label(current_dir_frame, text="Current Directory:", width=20).pack(side="left", padx=(0, 10))
        
        # Dataset directory variable
        self.dataset_dir_var = tk.StringVar(value="data/depth_dataset")
        dir_label = ttk.Label(current_dir_frame, textvariable=self.dataset_dir_var, 
                            font=("Segoe UI", 10, "italic"))
        dir_label.pack(side="left", fill="x", expand=True)
        
        # Directory Selection Button
        select_dir_frame = ttk.Frame(dir_frame)
        select_dir_frame.pack(fill="x", pady=5)
        
        # Directory Selection Button
        select_dir_btn = ttk.Button(select_dir_frame, 
                                 text="Select Directory", 
                                 command=self._select_dataset_directory)
        select_dir_btn.pack(fill="x")
        
        # Batch Information Section
        batch_frame = ttk.LabelFrame(parent, text="Batch Information", padding=15, labelanchor="n")
        batch_frame.pack(fill="x", pady=10, padx=5)
        
        # Single row for batch numbers, side by side
        batch_numbers_frame = ttk.Frame(batch_frame)
        batch_numbers_frame.pack(fill="x", pady=5)
        
        # Current batch number (left side)
        ttk.Label(batch_numbers_frame, text="Current Batch:", width=15).pack(side="left", padx=(0, 5))
        self.current_batch_var = tk.StringVar(value="N/A")
        ttk.Label(batch_numbers_frame, textvariable=self.current_batch_var, 
                font=("Segoe UI", 10, "bold"), width=8).pack(side="left", padx=(0, 15))
        
        # Scene batch number (right side)
        ttk.Label(batch_numbers_frame, text="Scene Batch:", width=15).pack(side="left", padx=(5, 5))
        self.scene_batch_var = tk.StringVar(value="N/A")
        ttk.Label(batch_numbers_frame, textvariable=self.scene_batch_var, 
                font=("Segoe UI", 10, "bold"), width=8).pack(side="left")
        
        # Refresh button
        refresh_btn = ttk.Button(batch_frame,
                               text="Refresh Batch Information",
                               command=self._update_batch_numbers)
        refresh_btn.pack(fill="x", pady=5)
        
        # Remove Recent Batches button
        self.remove_batches_btn = ttk.Button(batch_frame,
                                     text="Remove Batches From Current Scene",
                                     command=self._remove_current_scene_batches,
                                     style="Cancel.TButton")
        self.remove_batches_btn.pack(fill="x", pady=5)
        
        # Initially disable the button until scene is cleared
        self.remove_batches_btn.configure(state="disabled")
        
        # Tools Section
        viewer_frame = ttk.LabelFrame(parent, text="Tools", padding=15, labelanchor="n")
        viewer_frame.pack(fill="x", pady=10, padx=5)
        
        ttk.Label(viewer_frame, text="Open the depth image viewer to examine and manipulate captured depth images.",
                wraplength=500, justify="left").pack(pady=5)
        
        open_viewer_btn = ttk.Button(viewer_frame,
                                   text="Open Depth Image Viewer",
                                   command=self._open_depth_image_viewer)
        open_viewer_btn.pack(fill="x", pady=10)
        
        # Status variable for operations (we'll keep this for directory changes and other operations)
        self.dataset_status_var = tk.StringVar(value="Ready")
        self.dataset_status_label = ttk.Label(parent, textvariable=self.dataset_status_var,
                                           font=("Segoe UI", 10))
        self.dataset_status_label.pack(pady=10)
        
    def _update_batch_numbers(self):
        """Update the batch number information from files"""
        try:
            # Get depth collector
            depth_collector = SC.get_depth_collector()
            if not depth_collector:
                self.current_batch_var.set("N/A - Create scene first")
                self.scene_batch_var.set("N/A - Create scene first")
                return
                
            # Get the dataset directory
            dataset_dir = self.dataset_dir_var.get()
            
            # Read current batch number from batch_counter.txt
            current_batch = "0"
            batch_counter_file = os.path.join(dataset_dir, "batch_counter.txt")
            if os.path.exists(batch_counter_file):
                try:
                    with open(batch_counter_file, "r") as f:
                        current_batch = f.read().strip()
                except Exception as e:
                    self.logger.warning("MenuSystem", f"Error reading batch counter: {e}")
            
            # Read scene batch number from scene_batch_number.txt
            scene_batch = "N/A"
            scene_batch_file = os.path.join(dataset_dir, "scene_batch_number.txt")
            if os.path.exists(scene_batch_file):
                try:
                    with open(scene_batch_file, "r") as f:
                        scene_batch = f.read().strip()
                except Exception as e:
                    self.logger.warning("MenuSystem", f"Error reading scene batch number: {e}")
            
            # Update UI variables
            self.current_batch_var.set(current_batch)
            self.scene_batch_var.set(scene_batch)
            
        except Exception as e:
            self.logger.error("MenuSystem", f"Error updating batch numbers: {e}")
            self.current_batch_var.set("Error")
            self.scene_batch_var.set("Error")
            
    def _save_config_to_dataset(self):
        """Save the current configuration to the dataset directory with a custom name"""
        try:
            # Get depth collector
            depth_collector = SC.get_depth_collector()
            if not depth_collector:
                self.config_status_var.set("No depth collector available. Please create a scene first.")
                self.root.after(3000, lambda: self.config_status_var.set(""))
                return
            
            # Create a dialog to get the custom name
            dialog = tk.Toplevel(self.root)
            dialog.title("Save Configuration As")
            dialog.geometry("450x390")  
            dialog.transient(self.root)
            dialog.grab_set()  # Modal
            
            # Set minimum size to match current size
            dialog.minsize(450, 390)
            
            # Center on parent
            dialog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
            dialog.geometry(f"+{x}+{y}")
            
            # Content
            content_frame = ttk.Frame(dialog, padding=35)  # Increased padding from 25 to 35
            content_frame.pack(fill=tk.BOTH, expand=True)
            
            # Description explaining the purpose
            ttk.Label(
                content_frame,
                text="Save your current configuration settings with a custom name for future reference. It will be saved to the dataset directory.",
                font=("Segoe UI", 11),  # Increased font size from 10 to 11
                wraplength=350,
                justify="center"
            ).pack(pady=(0, 10))
            
            # Add note about controls being included
            ttk.Label(
                content_frame,
                text="Note: All settings including control mappings will be saved.",
                font=("Segoe UI", 10, "italic"),
                wraplength=350,
                foreground="#666666",
                justify="center"
            ).pack(pady=(0, 10))
            
            ttk.Label(
                content_frame, 
                text="Enter a name for this configuration:",
                font=("Segoe UI", 12)  # Increased font size from 11 to 12
            ).pack(pady=(0, 20))  # Increased bottom padding from 15 to 20
            
            # Entry for custom name
            name_var = tk.StringVar(value="config")
            name_entry = ttk.Entry(content_frame, textvariable=name_var, width=30, font=("Segoe UI", 12))  # Increased font size from 11 to 12
            name_entry.pack(fill=tk.X, pady=20, ipady=5)  # Increased padding from 15 to 20 and ipady from 3 to 5
            name_entry.focus_set()  # Set focus to the entry
            
            # Help text
            ttk.Label(
                content_frame,
                text="The file will be saved in the config subfolder of your dataset directory.",
                font=("Segoe UI", 10),  # Increased font size from 9 to 10
                foreground="#666666"
            ).pack(pady=(0, 25))  # Increased bottom padding from 15 to 25
            
            # Buttons
            button_frame = ttk.Frame(content_frame)
            button_frame.pack(fill=tk.X, pady=20)  # Increased padding from 15 to 20
            
            cancel_btn = ttk.Button(
                button_frame, 
                text="Cancel", 
                command=dialog.destroy
            )
            cancel_btn.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X, ipady=4)
            
            save_btn = ttk.Button(
                button_frame, 
                text="Save", 
                style="Apply.TButton",
                command=lambda: self._save_config_with_name(dialog, name_var.get(), depth_collector)
            )
            save_btn.pack(side=tk.RIGHT, padx=10, expand=True, fill=tk.X, ipady=4)  
            
            # Bind Enter key to save button
            dialog.bind("<Return>", lambda event: save_btn.invoke())
            
        except Exception as e:
            self.logger.error("MenuSystem", f"Error creating save dialog: {e}")
            self.config_status_var.set(f"Error: {str(e)}")
            self.root.after(3000, lambda: self.config_status_var.set(""))
    
    def _save_config_with_name(self, dialog, name, depth_collector):
        """Save the configuration with the provided name"""
        dialog.destroy()  # Close the dialog
        
        # Ensure we have the latest config with all settings from UI elements
        self._apply_all_config_changes()
        
        # Create a complete copy of the configuration
        complete_config = dict(self.config)
        
        # Update with any UI values not yet applied
        for key, var in self._config_vars.items():
            if isinstance(var, tk.BooleanVar):
                complete_config[key] = var.get()
            else:
                try:
                    # Try to convert to float if possible
                    complete_config[key] = float(var.get())
                except ValueError:
                    # If not a number, save as string
                    complete_config[key] = var.get()
        
        # Update any RC controller settings from the RC settings object if it exists
        if hasattr(self, 'rc_settings') and self.rc_settings:
            # Get RC settings and add them to the configuration
            if hasattr(self.rc_settings, 'get_settings'):
                rc_config = self.rc_settings.get_settings()
                for key, value in rc_config.items():
                    complete_config[key] = value
        
        # Add a message to the config indicating it includes RC settings
        complete_config['includes_rc_settings'] = True
        
        # Save configuration with custom name
        filepath = depth_collector.save_config_to_json(complete_config, name)
        if filepath:
            self.config_status_var.set(f"All settings (including controls) saved to: {os.path.basename(filepath)}")
            self.root.after(3000, lambda: self.config_status_var.set(""))
        else:
            self.config_status_var.set("Error saving configuration")
            self.root.after(3000, lambda: self.config_status_var.set(""))
    
    def _select_dataset_directory(self):
        """Select a directory for dataset storage"""
        try:
            directory = filedialog.askdirectory(
                title="Select Dataset Directory",
                initialdir="data/depth_dataset"
            )
            
            if directory:
                self.logger.debug_at_level(DEBUG_L1, "MenuSystem", f"Selected dataset directory: {directory}")
                
                # Get depth collector
                depth_collector = SC.get_depth_collector()
                if not depth_collector:
                    self.logger.warning("MenuSystem", "No depth collector available. Please create a scene first.")
                    self.status_label.configure(text="No depth collector available. Please create a scene first.")
                    self.root.after(3000, lambda: self.status_label.configure(text=""))
                    return
                    
                # Set new base folder
                depth_collector.set_base_folder(directory)
                
                # Update the UI
                self.dataset_dir_var.set(directory)
                self.status_label.configure(text=f"Dataset directory set to: {directory}")
                self.root.after(3000, lambda: self.status_label.configure(text=""))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error setting dataset directory: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))
    
    def _safe_ui_update(self, function):
        """Safely update the UI from any thread"""
        if not hasattr(self, 'root') or not self.root:
            self.logger.warning("MenuSystem", "Cannot update UI - window no longer exists")
            return
            
        # If we're in the main thread, just execute the function
        if threading.current_thread() is threading.main_thread():
            try:
                function()
            except tk.TclError as e:
                if "main thread is not in main loop" in str(e):
                    self.logger.warning("MenuSystem", "Cannot update UI - main thread is not in main loop")
                else:
                    self.logger.error("MenuSystem", f"Tkinter error in UI update: {e}")
            except Exception as e:
                self.logger.error("MenuSystem", f"Error in UI update: {e}")
        else:
            # We're in a background thread, schedule the update on the main thread
            try:
                # Only schedule if the root window exists and is in mainloop
                if hasattr(self, 'root') and self.root.winfo_exists():
                    # Use after(0) instead of after_idle for more reliable execution
                    self.root.after(0, function)
                else:
                    self.logger.warning("MenuSystem", "Cannot schedule UI update - window no longer exists or mainloop not running")
            except tk.TclError as e:
                # If we get an error about main thread not in main loop, 
                # we'll ignore it as it's expected from background threads
                if "main thread is not in main loop" not in str(e):
                    self.logger.error("MenuSystem", f"Error scheduling UI update: {e}")
            except Exception as e:
                self.logger.error("MenuSystem", f"Error scheduling UI update: {e}")

    def _on_batch_saved(self, data):
        """Handle batch saved event"""
        # Check if UI is still active before attempting update
        if not hasattr(self, 'root') or not self.root.winfo_exists():
            return
        
        # Extract relevant data safely
        batch_id = data.get('batch_id', 0)
        count = data.get('count', 0)
        total_saved = data.get('total_saved', 0)
        is_bg_thread = data.get('is_background_thread', False)
        
        def update_ui():
            try:
                if hasattr(self, 'dataset_status_label'):
                    self.dataset_status_label.config(
                        text=f"Saved batch {batch_id} ({count} images)"
                    )
                
                if hasattr(self, 'dataset_stats_label'):
                    self.dataset_stats_label.config(
                        text=f"Total: {total_saved} images"
                    )
                    
                # Update batch number display if we have the variable
                if hasattr(self, 'current_batch_var'):
                    self.current_batch_var.set(str(batch_id))
                    
                # Optionally refresh all batch information
                if self._current_tab == "Dataset" and hasattr(self, '_update_batch_numbers'):
                    self._update_batch_numbers()
                    
            except Exception as e:
                # Don't log TclError about main thread, as these are expected
                if not isinstance(e, tk.TclError) or "main thread is not in main loop" not in str(e):
                    self.logger.error("MenuSystem", f"Error updating batch save status: {e}")
        
        # Handle differently based on thread
        if is_bg_thread:
            try:
                # For background threads, only attempt if root exists and use idletasks
                if hasattr(self, 'root') and self.root.winfo_exists():
                    # Schedule with a longer delay to avoid threading issues
                    self.root.after(500, update_ui)
            except Exception as e:
                # Completely ignore main thread errors - these are expected from background threads
                pass
        else:
            # Use normal update for main thread
            try:
                self._safe_ui_update(update_ui)
            except Exception as e:
                # Silently ignore errors from UI updates
                pass

    def _on_dataset_config_updated(self, data):
        """Handle dataset config updated event"""
        # Check if UI is still active before attempting update
        if not hasattr(self, 'root') or not self.root.winfo_exists():
            return
            
        def update_ui():
            try:
                if hasattr(self, 'dataset_dir_label'):
                    self.dataset_dir_label.config(
                        text=f"Directory: {data['base_folder']}"
                    )
            except Exception as e:
                self.logger.error("MenuSystem", f"Error updating dataset directory display: {e}")
        
        self._safe_ui_update(update_ui)

    def _build_logging_tab(self, parent):
        """Build the logging tab with log level controls and log view"""
        # Create a ScrollFrame for the logging content
        scroll_frame = ScrollFrame(parent, bg="#0a0a0a")
        scroll_frame.pack(fill="both", expand=True)
        
        # Get the scrollable frame to add content to
        scrollable_frame = scroll_frame.scrollable_frame
        
        # Title
        title_label = ttk.Label(
            scrollable_frame, 
            text="Logging Configuration", 
            style="Title.TLabel"
        )
        title_label.pack(pady=(0, 20))
        
        # Log Level selection section
        log_level_frame = ttk.LabelFrame(scrollable_frame, text="Log Level", labelanchor="n", padding=15)
        log_level_frame.pack(fill="x", padx=5, pady=10)
        
        log_level_content = ttk.Frame(log_level_frame)
        log_level_content.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(log_level_content, text="Select log level:").pack(side="left", padx=(0, 10))
        
        # Create the dropdown for log levels
        self.log_level_var = tk.StringVar(value="INFO")
        log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        level_dropdown = ttk.Combobox(
            log_level_content, 
            textvariable=self.log_level_var, 
            values=log_levels, 
            state="readonly",
            width=10
        )
        level_dropdown.pack(side="left", padx=5)
        
        # Button to apply the log level change
        apply_level_btn = ttk.Button(
            log_level_content, 
            text="Apply", 
            command=self._change_log_level,
            style="Apply.TButton"
        )
        apply_level_btn.pack(side="left", padx=10)
        
        # Current log level display
        self.current_level_label = ttk.Label(log_level_content, text="Current: INFO")
        self.current_level_label.pack(side="right", padx=10)
        
        # Debug Level selection section
        debug_level_frame = ttk.LabelFrame(scrollable_frame, text="Debug Verbosity", labelanchor="n", padding=15)
        debug_level_frame.pack(fill="x", padx=5, pady=10)
        
        debug_level_content = ttk.Frame(debug_level_frame)
        debug_level_content.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(debug_level_content, text="Select debug verbosity:").pack(anchor="w", pady=(0, 5))
        
        # Description of debug levels
        debug_desc_frame = ttk.Frame(debug_level_content)
        debug_desc_frame.pack(fill="x", pady=5)
        
        ttk.Label(debug_desc_frame, text="L1 - Basic: High-level info and important events").pack(anchor="w")
        ttk.Label(debug_desc_frame, text="L2 - Medium: Detailed operations and parameters").pack(anchor="w")
        ttk.Label(debug_desc_frame, text="L3 - Verbose: All events including frequent updates").pack(anchor="w")
        
        # Debug level radio buttons
        debug_selection_frame = ttk.Frame(debug_level_content)
        debug_selection_frame.pack(fill="x", pady=10)
        
        self.debug_level_var = tk.IntVar(value=1)
        debug_levels = [(1, "L1 (Basic)"), (2, "L2 (Medium)"), (3, "L3 (Verbose)")]
        
        for level, text in debug_levels:
            rb = ttk.Radiobutton(
                debug_selection_frame, 
                text=text, 
                variable=self.debug_level_var, 
                value=level
            )
            rb.pack(side="left", padx=10)
        
        # Apply debug level button
        apply_debug_btn = ttk.Button(
            debug_level_content, 
            text="Apply Debug Level", 
            command=self._change_debug_level,
            style="Apply.TButton"
        )
        apply_debug_btn.pack(pady=10)
        
        # Current debug level display
        self.current_debug_label = ttk.Label(debug_level_content, text="Current: L1 (Basic)")
        self.current_debug_label.pack(pady=5)
        
        # File Logging section
        file_logging_frame = ttk.LabelFrame(scrollable_frame, text="File Logging", labelanchor="n", padding=15)
        file_logging_frame.pack(fill="x", padx=5, pady=10)
        
        file_logging_content = ttk.Frame(file_logging_frame)
        file_logging_content.pack(fill="x", padx=10, pady=10)
        
        # File logging toggle
        self.file_logging_var = tk.BooleanVar(value=False)
        file_logging_chk = ttk.Checkbutton(
            file_logging_content, 
            text="Enable File Logging", 
            variable=self.file_logging_var
        )
        file_logging_chk.pack(anchor="w", pady=5)
        
        # Logs directory display
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
        logs_dir_frame = ttk.Frame(file_logging_content)
        logs_dir_frame.pack(fill="x", pady=5)
        
        ttk.Label(logs_dir_frame, text="Logs directory:").pack(side="left", padx=(0, 5))
        self.logs_dir_label = ttk.Label(logs_dir_frame, text=logs_dir)
        self.logs_dir_label.pack(side="left", padx=5)
        
        # Apply file logging button
        apply_file_logging_btn = ttk.Button(
            file_logging_content, 
            text="Apply File Logging Setting", 
            command=self._toggle_file_logging,
            style="Apply.TButton"
        )
        apply_file_logging_btn.pack(pady=10)
        
        # Logging status display
        self.file_logging_status = ttk.Label(
            file_logging_content, 
            text="File logging is currently disabled"
        )
        self.file_logging_status.pack(pady=5)
        
        # Open logs directory button
        open_logs_btn = ttk.Button(
            file_logging_content, 
            text="Open Logs Directory", 
            command=self._open_logs_directory
        )
        open_logs_btn.pack(pady=10)
        
        # Verbose mode section
        verbose_frame = ttk.LabelFrame(scrollable_frame, text="Verbose Mode", labelanchor="n", padding=15)
        verbose_frame.pack(fill="x", padx=5, pady=10)
        
        verbose_content = ttk.Frame(verbose_frame)
        verbose_content.pack(fill="x", padx=10, pady=10)
        
        # Verbose mode toggle
        self.verbose_var = tk.BooleanVar(value=False)
        verbose_chk = ttk.Checkbutton(
            verbose_content, 
            text="Enable Verbose Logging", 
            variable=self.verbose_var
        )
        verbose_chk.pack(anchor="w", pady=5)
        
        # Description of verbose mode
        ttk.Label(
            verbose_content, 
            text="Verbose mode enables detailed logging at DEBUG level with all debug messages",
            wraplength=500
        ).pack(pady=5)
        
        # Apply verbose mode button
        apply_verbose_btn = ttk.Button(
            verbose_content, 
            text="Apply Verbose Setting", 
            command=self._toggle_verbose_mode,
            style="Apply.TButton"
        )
        apply_verbose_btn.pack(pady=10)
        
        # The ScrollFrame class now handles all scrolling, so we don't need these canvas-related lines
        
        # Initialize the logger display with current settings
        self._update_logging_status()
    
    def _update_logging_status(self):
        """Update the logging status labels based on current settings."""
        # This function is called from the main thread UI handlers
        try:
            # Get instance from the actual Logger class
            from Utils.log_utils import get_logger
            logger_instance = get_logger()
            
            # Debug logging for diagnostics
            self.logger.info("MenuSystem", f"Logger type: {type(logger_instance).__name__}")
            
            # Get console handler level - the fork uses console_handler property
            if hasattr(logger_instance, 'console_handler') and hasattr(logger_instance.console_handler, 'level'):
                level = logger_instance.console_handler.level
                self.logger.info("MenuSystem", f"Console handler level: {level}")
                
                # Use the logger's own _level_to_name method if available
                if hasattr(logger_instance, '_level_to_name') and callable(logger_instance._level_to_name):
                    level_name = logger_instance._level_to_name(level)
                else:
                    level_name = self._level_to_name(level)
                    
                self.logger.info("MenuSystem", f"Level name: {level_name}")
                self.current_level_label.config(text=f"Current: {level_name}")
                self.log_level_var.set(level_name)
            else:
                self.logger.warning("MenuSystem", "Could not access console_handler.level")
                self.current_level_label.config(text="Current: Unknown")
                self.log_level_var.set("INFO")  # Default fallback
            
            # Update debug level label
            if hasattr(logger_instance, 'current_debug_level'):
                debug_level = logger_instance.current_debug_level
                self.logger.info("MenuSystem", f"Debug level: {debug_level}")
                debug_names = {1: "L1 (Basic)", 2: "L2 (Medium)", 3: "L3 (Verbose)"}
                self.current_debug_label.config(text=f"Current: {debug_names.get(debug_level, 'Unknown')}")
                self.debug_level_var.set(debug_level)
            else:
                self.logger.warning("MenuSystem", "Could not access current_debug_level")
                self.current_debug_label.config(text="Current: L1 (Basic)")
                self.debug_level_var.set(1)  # Default fallback
            
            # Update file logging status
            has_file_logging = hasattr(logger_instance, 'file_handler') and logger_instance.file_handler is not None
            self.file_logging_var.set(has_file_logging)
            
            if has_file_logging and hasattr(logger_instance.file_handler, 'baseFilename'):
                log_file = logger_instance.file_handler.baseFilename
                self.file_logging_status.config(text=f"File logging enabled: {os.path.basename(log_file)}")
            else:
                self.file_logging_status.config(text="File logging is currently disabled")
            
            # Update verbose mode status
            if hasattr(logger_instance, 'verbose'):
                self.verbose_var.set(logger_instance.verbose)
            else:
                self.verbose_var.set(False)  # Default fallback
                
        except Exception as e:
            self.logger.error("MenuSystem", f"Error updating logging status: {e}")
            self.status_label.configure(text=f"Error updating logging status: {str(e)}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
    
    def _change_debug_level(self):
        """Change the debug verbosity level from the UI."""
        try:
            level = self.debug_level_var.get()
            self.logger.info("MenuSystem", f"Changing debug level to: {level}")
            
            if level in [DEBUG_L1, DEBUG_L2, DEBUG_L3]:
                # Get instance from the actual Logger class
                from Utils.log_utils import get_logger
                logger_instance = get_logger()
                
                # Use the set_debug_level method
                logger_instance.set_debug_level(level)
                
                level_names = {DEBUG_L1: "Basic", DEBUG_L2: "Medium", DEBUG_L3: "Verbose"}
                self.logger.info("MenuSystem", f"Debug level changed to L{level} ({level_names[level]})")
                
                # Update UI immediately since we're in the main thread
                self._update_logging_status()
                self.status_label.configure(text=f"Debug level changed to L{level} ({level_names[level]})")
                self.root.after(2000, lambda: self.status_label.configure(text=""))
            else:
                self.logger.error("MenuSystem", f"Invalid debug level: {level}")
                self.status_label.configure(text=f"Error: Invalid debug level")
                self.root.after(2000, lambda: self.status_label.configure(text=""))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error changing debug level: {e}")
            self.status_label.configure(text=f"Error changing debug level: {str(e)}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
    
    def _toggle_file_logging(self):
        """Toggle file logging on or off from the UI."""
        # This already runs in the main thread, so no need for _safe_ui_update
        try:
            enabled = self.file_logging_var.get()
            self.logger.info("MenuSystem", f"Setting file logging to: {enabled}")
            
            # Get instance from the actual Logger class
            from Utils.log_utils import get_logger
            logger_instance = get_logger()
            
            if enabled:
                # Create logs directory if it doesn't exist
                logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
                os.makedirs(logs_dir, exist_ok=True)
                
                # Generate filename with timestamp
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"disaster_sim_{timestamp}.log"
                
                # Configure file logging
                logger_instance.configure_file_logging(enabled=True, level=LOG_LEVEL_DEBUG, filename=filename)
                self.logger.info("MenuSystem", f"File logging enabled: {filename}")
                self.status_label.configure(text=f"File logging enabled: {filename}")
            else:
                logger_instance.configure_file_logging(enabled=False)
                self.logger.info("MenuSystem", "File logging disabled")
                self.status_label.configure(text="File logging disabled")
                
            # Update UI immediately since we're in the main thread
            self._update_logging_status()
            self.root.after(3000, lambda: self.status_label.configure(text=""))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error configuring file logging: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))
            
    def _toggle_verbose_mode(self):
        """Toggle verbose mode on or off from the UI."""
        try:
            verbose = self.verbose_var.get()
            self.logger.info("MenuSystem", f"Setting verbose mode to: {verbose}")
            
            # Get instance from the actual Logger class
            from Utils.log_utils import get_logger
            logger_instance = get_logger()
            
            # Configure logger with new verbose setting
            console_level = LOG_LEVEL_DEBUG if verbose else LOG_LEVEL_INFO
            debug_level = self.debug_level_var.get()
            
            logger_instance.configure(
                verbose=verbose,
                console_level=console_level,
                debug_level=debug_level,
                colored_output=True
            )
            
            # Show appropriate message
            message = "Verbose mode enabled" if verbose else "Verbose mode disabled"
            self.logger.info("MenuSystem", message)
            self.status_label.configure(text=message)
            
            # Update UI immediately since we're in the main thread
            self._update_logging_status()
            self.root.after(2000, lambda: self.status_label.configure(text=""))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error setting verbose mode: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
    
    def _open_logs_directory(self):
        """Open the logs directory in the file explorer."""
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        try:
            if platform.system() == "Windows":
                os.startfile(logs_dir)
            elif platform.system() == "Darwin":  # macOS
                import subprocess
                subprocess.call(["open", logs_dir])
            else:  # Linux
                import subprocess
                subprocess.call(["xdg-open", logs_dir])
        except Exception as e:
            self.logger.error("MenuSystem", f"Error opening logs directory: {e}")

    def _change_log_level(self):
        """Change the logging level from the UI."""
        # This runs in the main thread, so no need for _safe_ui_update
        try:
            level_str = self.log_level_var.get()
            self.logger.info("MenuSystem", f"Trying to change log level to: {level_str}")
            
            # Map level names to standard Python logging levels
            level_map = {
                "DEBUG": LOG_LEVEL_DEBUG,
                "INFO": LOG_LEVEL_INFO,
                "WARNING": LOG_LEVEL_WARNING,
                "ERROR": LOG_LEVEL_ERROR,
                "CRITICAL": LOG_LEVEL_CRITICAL
            }
            
            if level_str in level_map:
                level = level_map[level_str]
                self.logger.info("MenuSystem", f"Mapped level name {level_str} to value {level}")
                
                # Get the logger instance directly to ensure we're using the right object
                from Utils.log_utils import get_logger
                logger_instance = get_logger()
                
                try:
                    # Use the proper set_level method
                    logger_instance.set_level(level)
                    self.logger.info("MenuSystem", f"Log level changed to {level_str}")
                    
                    # Generate a test message at the selected level to verify the change
                    if level_str == "DEBUG":
                        logger_instance.debug("MenuSystem", f"TEST: This is a DEBUG message")
                    elif level_str == "INFO":
                        logger_instance.info("MenuSystem", f"TEST: This is an INFO message")
                    elif level_str == "WARNING":
                        logger_instance.warning("MenuSystem", f"TEST: This is a WARNING message")
                    elif level_str == "ERROR":
                        logger_instance.error("MenuSystem", f"TEST: This is an ERROR message")
                    elif level_str == "CRITICAL":
                        logger_instance.critical("MenuSystem", f"TEST: This is a CRITICAL message")
                    
                    # Update UI immediately since we're in the main thread
                    self._update_logging_status()
                    self.status_label.configure(text=f"Log level changed to {level_str} (test message sent)")
                    self.root.after(2000, lambda: self.status_label.configure(text=""))
                except Exception as e:
                    self.logger.error("MenuSystem", f"Error setting log level: {e}")
                    self.status_label.configure(text=f"Error: {str(e)}")
                    self.root.after(2000, lambda: self.status_label.configure(text=""))
            else:
                self.logger.error("MenuSystem", f"Invalid log level: {level_str}")
                self.status_label.configure(text=f"Error: Invalid log level")
                self.root.after(2000, lambda: self.status_label.configure(text=""))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error changing log level: {e}")
            self.status_label.configure(text=f"Error changing log level: {str(e)}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))

    def _level_to_name(self, level):
        """Convert logging level integer to name."""
        try:
            # Log the level we're trying to convert for debugging
            self.logger.info("MenuSystem", f"Converting level value: {level} (type: {type(level).__name__})")
            
            # Handle the case when level is 0
            if level == 0:
                self.logger.warning("MenuSystem", "Received level 0, defaulting to INFO")
                return "INFO"
                
            # Standard logging levels
            if level == LOG_LEVEL_DEBUG:
                return "DEBUG"
            elif level == LOG_LEVEL_INFO:
                return "INFO"
            elif level == LOG_LEVEL_WARNING:
                return "WARNING"
            elif level == LOG_LEVEL_ERROR:
                return "ERROR"
            elif level == LOG_LEVEL_CRITICAL:
                return "CRITICAL"
            
            # Handle other common level values that might be used
            elif level == 10:  # Common value for DEBUG
                return "DEBUG"
            elif level == 20:  # Common value for INFO
                return "INFO"
            elif level == 30:  # Common value for WARNING
                return "WARNING"
            elif level == 40:  # Common value for ERROR
                return "ERROR"
            elif level == 50:  # Common value for CRITICAL
                return "CRITICAL"
            else:
                self.logger.warning("MenuSystem", f"Unknown log level value: {level}")
                return f"UNKNOWN ({level})"
        except Exception as e:
            self.logger.error("MenuSystem", f"Error converting log level to name: {e}")
            return "UNKNOWN"

    def _build_controls_tab(self, parent):
        """Build the controls tab with both keyboard and RC settings"""
        # Create a ScrollFrame for the controls options
        scroll_frame = ScrollFrame(parent, bg="#0a0a0a")
        scroll_frame.pack(fill="both", expand=True)
        
        # Get the scrollable frame to add content to
        scrollable_frame = scroll_frame.scrollable_frame
        
        # Movement Mode Section
        movement_mode_frame = ttk.LabelFrame(scrollable_frame, text="Movement Mode", padding=15, labelanchor="n")
        movement_mode_frame.pack(fill="x", pady=10, padx=5)
        
        # Create a variable to track the movement mode
        self.single_axis_mode_var = tk.BooleanVar(value=self.config.get("single_axis_mode", False))
        
        # Create a checkbox for single-axis mode
        single_axis_check = ttk.Checkbutton(
            movement_mode_frame,
            text="Single-Axis Movement Mode",
            variable=self.single_axis_mode_var,
            command=self._toggle_single_axis_mode
        )
        single_axis_check.pack(anchor="w", pady=5)
        
        # Add description text
        description_text = """When enabled, the drone will only move along one axis at a time.
This is useful for dataset collection where you want clean, isolated movements.
The axis with the largest input will be active, and all others will be disabled.
For example:
- If you use the pitch control (W/S), all other controls will be disabled
- If you then use the yaw control (Q/E), the pitch control will stop and only yaw will be active
- Only one movement axis can be active at any time"""
        
        ttk.Label(
            movement_mode_frame,
            text=description_text,
            justify="left",
            wraplength=500
        ).pack(padx=10, pady=5, anchor="w")
        
        # Apply movement mode button
        apply_mode_btn = ttk.Button(
            movement_mode_frame,
            text="Apply Movement Mode",
            command=self._apply_movement_mode,
            style="Apply.TButton"
        )
        apply_mode_btn.pack(pady=10)
        
        # Keyboard Controls Section
        keyboard_frame = ttk.LabelFrame(scrollable_frame, text="Keyboard Controls", padding=15, labelanchor="n")
        keyboard_frame.pack(fill="x", pady=10, padx=5)
        
        # Create a keyboard controls info display
        key_info = """Movement Controls:"""
        
        ttk.Label(
            keyboard_frame,
            text=key_info,
            justify="left",
            wraplength=500
        ).pack(padx=10, pady=5, anchor="w")
        
        # Keyboard sensitivity settings
        key_settings_frame = ttk.Frame(keyboard_frame)
        key_settings_frame.pack(fill="x", pady=10)
        
        # Move step (keyboard sensitivity)
        move_frame = ttk.Frame(key_settings_frame)
        move_frame.pack(fill="x", pady=5)
        
        ttk.Label(
            move_frame,
            text="Movement Speed:",
            width=20
        ).pack(side="left")
        
        # Move step slider
        self.move_step_var = tk.DoubleVar(value=self.config.get("move_step", 0.2))
        move_scale = ttk.Scale(
            move_frame,
            from_=0.01,
            to=0.3,
            orient="horizontal",
            variable=self.move_step_var,
            command=self._update_move_step_label
        )
        move_scale.pack(side="left", fill="x", expand=True, padx=5)
        
        self.move_step_label = ttk.Label(
            move_frame,
            text=f"{self.move_step_var.get():.2f}",
            width=5
        )
        self.move_step_label.pack(side="left", padx=5)
        
        # Rotate step (rotation speed)
        rotate_frame = ttk.Frame(key_settings_frame)
        rotate_frame.pack(fill="x", pady=5)
        
        ttk.Label(
            rotate_frame,
            text="Rotation Speed:",
            width=20
        ).pack(side="left")
        
        # Rotate step slider
        self.rotate_step_var = tk.DoubleVar(value=self.config.get("rotate_step_deg", 15.0))
        rotate_scale = ttk.Scale(
            rotate_frame,
            from_=5.0,
            to=40.0,
            orient="horizontal",
            variable=self.rotate_step_var,
            command=self._update_rotate_step_label
        )
        rotate_scale.pack(side="left", fill="x", expand=True, padx=5)
        
        self.rotate_step_label = ttk.Label(
            rotate_frame,
            text=f"{self.rotate_step_var.get():.1f}°",
            width=5
        )
        self.rotate_step_label.pack(side="left", padx=5)
        
        # Apply keyboard settings button
        apply_keyboard_btn = ttk.Button(
            keyboard_frame,
            text="Apply Keyboard Settings",
            command=self._apply_keyboard_settings,
            style="Apply.TButton"
        )
        apply_keyboard_btn.pack(pady=10)
        
        # RC Controller Section
        # Create an instance of RCControllerSettings
        self.rc_settings = RCControllerSettings(scrollable_frame, self.config)
        
        # The ScrollFrame class now handles all scrolling, so we don't need these lines anymore
        # that referred to the canvas variable which no longer exists
    
    def _update_move_step_label(self, value):
        """Update the movement speed value label"""
        try:
            val = float(value)
            # Changed to 2 decimal places for more precise display of values like 0.05
            self.move_step_label.config(text=f"{val:.2f}")
        except:
            pass
    
    def _update_rotate_step_label(self, value):
        """Update the rotation speed value label"""
        try:
            val = float(value)
            self.rotate_step_label.config(text=f"{val:.1f}°")
        except:
            pass
    
    def _apply_keyboard_settings(self):
        """Apply keyboard control settings"""
        try:
            # Update config with current UI values, rounding to appropriate decimals
            # Changed rounding from 1 to 2 decimal places to preserve values like 0.05
            move_step_value = round(self.move_step_var.get(), 2)
            rotate_step_value = round(self.rotate_step_var.get(), 1)
            
            # Preserve previous non-zero move_step value if new value is zero
            if move_step_value == 0.0 and "move_step" in self.config and self.config["move_step"] > 0:
                self.logger.info("MenuSystem", f"Preserving non-zero move_step value: {self.config['move_step']}")
            else:
                self.config["move_step"] = move_step_value
                self.logger.info("MenuSystem", f"Set move_step value: {move_step_value}")
                
            self.config["rotate_step_deg"] = rotate_step_value
            
            # Publish config update events
            EM.publish('config/updated', 'move_step')
            EM.publish('config/updated', 'rotate_step_deg')
            
            # Show confirmation via status label - updated to 2 decimal places
            self.status_label.configure(text=f"Keyboard settings updated: move_step={self.config['move_step']:.2f}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            
            self.logger.info("MenuSystem", f"Updated keyboard settings: move_step={self.config['move_step']}, rotate_step_deg={self.config['rotate_step_deg']}")
        except Exception as e:
            self.status_label.configure(text=f"Error updating keyboard settings: {e}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            self.logger.error("MenuSystem", f"Error updating keyboard settings: {e}")

    def _toggle_single_axis_mode(self):
        """Toggle single-axis mode on or off from the UI."""
        self.config["single_axis_mode"] = self.single_axis_mode_var.get()
        self.logger.info("MenuSystem", f"Single-axis mode {'enabled' if self.single_axis_mode_var.get() else 'disabled'}")
        self.status_label.configure(text=f"Single-axis mode {'enabled' if self.single_axis_mode_var.get() else 'disabled'}")
        self.root.after(2000, lambda: self.status_label.configure(text=""))

    def _apply_movement_mode(self):
        """Apply movement mode settings"""
        try:
            # Update config with current UI values
            self.config["single_axis_mode"] = self.single_axis_mode_var.get()
            
            # Publish config update event
            EM.publish('config/updated', 'single_axis_mode')
            
            # Show confirmation via status label
            self.status_label.configure(text=f"Movement mode updated: {'Single-axis' if self.single_axis_mode_var.get() else 'Multi-directional'}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            
            self.logger.info("MenuSystem", f"Updated movement mode: single_axis_mode={self.config['single_axis_mode']}")
        except Exception as e:
            self.status_label.configure(text=f"Error updating movement mode: {e}")
            self.root.after(2000, lambda: self.status_label.configure(text=""))
            self.logger.error("MenuSystem", f"Error updating movement mode: {e}")

    def _open_depth_image_viewer(self):
        """Open the depth image viewer tool"""
        try:
            # Get the correct path to the viewer tool
            import subprocess
            import os
            import sys
            
            # Get the path to the Tools directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            viewer_path = os.path.join(parent_dir, "Tools", "View_Depth_Image.py")
            
            # Check if the file exists
            if not os.path.exists(viewer_path):
                self.logger.error("MenuSystem", f"Depth image viewer not found at {viewer_path}")
                self.status_label.configure(text="Error: Depth image viewer tool not found")
                self.root.after(3000, lambda: self.status_label.configure(text=""))
                return
                
            # Get the current Python interpreter path
            python_executable = sys.executable
            
            # Launch the viewer tool with the current Python interpreter
            self.logger.info("MenuSystem", f"Launching depth image viewer from {viewer_path} with {python_executable}")
            subprocess.Popen([python_executable, viewer_path])
            
            # Show success message
            self.status_label.configure(text="Depth image viewer launched successfully")
            self.root.after(3000, lambda: self.status_label.configure(text=""))
        except Exception as e:
            self.logger.error("MenuSystem", f"Error opening depth image viewer: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))

    def _show_mapping_details(self, parent, mappings):
        """Show details of RC mappings in a popup dialog"""
        # Create popup dialog
        dialog = tk.Toplevel(parent)
        dialog.title("RC Mappings Details")
        dialog.geometry("400x300")
        dialog.transient(parent)  # Make dialog modal to parent
        dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Content frame
        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(
            frame,
            text="RC Controller Axis Mappings",
            font=("Segoe UI", 12, "bold"),
            foreground="#00b4d8"
        ).pack(pady=(0, 15))
        
        # Create table for mappings
        control_names = [("throttle", "Throttle"), ("yaw", "Yaw"), ("pitch", "Pitch"), ("roll", "Roll")]
        
        for control_id, display_name in control_names:
            # Get mapping for this control
            mapping = mappings.get(control_id, {})
            axis = mapping.get("axis", "Not mapped")
            inverted = mapping.get("invert", False)
            
            # Control row
            row_frame = ttk.Frame(frame)
            row_frame.pack(fill="x", pady=5)
            
            # Control name
            ttk.Label(
                row_frame,
                text=f"{display_name}:",
                width=15,
                font=("Segoe UI", 10, "bold")
            ).pack(side="left")
            
            # Axis number
            if axis == "Not mapped":
                axis_text = "Not mapped"
                axis_color = "#AA0000"  # Red for not mapped
            else:
                axis_text = f"Axis {axis}"
                axis_color = "#FFFFFF"  # White for mapped (was Black)
                
            ttk.Label(
                row_frame,
                text=axis_text,
                foreground=axis_color,
                width=12
            ).pack(side="left", padx=5)
            
            # Inversion indicator
            if axis != "Not mapped":
                invert_text = "Inverted" if inverted else "Normal"
                invert_color = "#AA6600" if inverted else "#00AA00"  # Orange if inverted, green if normal
                
                ttk.Label(
                    row_frame,
                    text=invert_text,
                    foreground=invert_color,
                    width=10
                ).pack(side="left", padx=5)
        
        # Close button
        ttk.Button(
            frame,
            text="Close",
            command=dialog.destroy,
            width=15
        ).pack(pady=15)

    def _remove_current_scene_batches(self):
        """Remove all batches created after the current scene batch number"""
        try:
            # Get depth collector
            depth_collector = SC.get_depth_collector()
            if not depth_collector:
                self.status_label.configure(text="No depth collector available. Please create a scene first.")
                self.root.after(3000, lambda: self.status_label.configure(text=""))
                return
            
            # Get the dataset directory
            dataset_dir = self.dataset_dir_var.get()
            
            # Get the current scene batch number
            scene_batch_file = os.path.join(dataset_dir, "scene_batch_number.txt")
            if not os.path.exists(scene_batch_file):
                self.status_label.configure(text="No scene batch number file found.")
                self.root.after(3000, lambda: self.status_label.configure(text=""))
                return
                
            # Read scene batch number
            try:
                with open(scene_batch_file, "r") as f:
                    scene_batch = f.read().strip()
                scene_batch = int(scene_batch)
            except Exception as e:
                self.logger.error("MenuSystem", f"Error reading scene batch number: {e}")
                self.status_label.configure(text=f"Error reading scene batch number: {str(e)}")
                self.root.after(3000, lambda: self.status_label.configure(text=""))
                return
            
            # Get current batch number
            batch_counter_file = os.path.join(dataset_dir, "batch_counter.txt")
            try:
                with open(batch_counter_file, "r") as f:
                    current_batch = int(f.read().strip())
            except Exception as e:
                self.logger.error("MenuSystem", f"Error reading batch counter: {e}")
                self.status_label.configure(text=f"Error reading batch counter: {str(e)}")
                self.root.after(3000, lambda: self.status_label.configure(text=""))
                return
            
            # Create a confirmation dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Confirm Batch Removal")
            dialog.geometry("400x200")
            dialog.transient(self.root)
            dialog.grab_set()  # Make dialog modal
            
            # Center dialog on parent window
            dialog.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
            dialog.geometry(f"+{x}+{y}")
            
            # Add padding frame
            frame = ttk.Frame(dialog, padding=20)
            frame.pack(expand=True, fill="both")
            
            # Warning message
            message = f"This will remove all batches from {scene_batch+1} to {current_batch}.\nAre you sure you want to continue?"
            ttk.Label(frame, 
                     text=message,
                     font=("Segoe UI", 11),
                     wraplength=350,
                     justify="center").pack(pady=(0, 20))
            
            # Buttons frame
            btn_frame = ttk.Frame(frame)
            btn_frame.pack(fill="x", pady=(0, 10))
            
            # No button
            no_btn = ttk.Button(btn_frame,
                             text="Cancel",
                             command=dialog.destroy)
            no_btn.pack(side="left", expand=True, padx=(0, 5), fill="both", ipady=5)
            
            # Yes button
            yes_btn = ttk.Button(btn_frame, 
                              text="Yes, Delete Batches",
                              style="Cancel.TButton",
                              command=lambda: self._confirm_remove_batches(dialog, scene_batch, current_batch))
            yes_btn.pack(side="left", expand=True, padx=(5, 0), fill="both", ipady=5)
            
        except Exception as e:
            self.logger.error("MenuSystem", f"Error preparing batch removal: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))
            
    def _confirm_remove_batches(self, dialog, scene_batch, current_batch):
        """Actually remove the batches after confirmation"""
        dialog.destroy()
        
        # Show progress in status bar
        self.status_label.configure(text="Removing batches... Please wait.")
        
        try:
            # Get the dataset directory
            dataset_dir = self.dataset_dir_var.get()
            
            # Define the batch counter file path
            batch_counter_file = os.path.join(dataset_dir, "batch_counter.txt")
            
            # Define the folders to check
            folders = ["train", "val", "test"]
            removed_count = 0
            
            # Process each folder
            for folder in folders:
                folder_path = os.path.join(dataset_dir, folder)
                if not os.path.exists(folder_path):
                    continue
                
                # Find batch files to remove (format: batch_000XXX.npz)
                for batch_id in range(scene_batch + 1, current_batch + 1):
                    # Format batch number with leading zeros (6 digits)
                    batch_str = f"{batch_id:06d}"
                    batch_file = os.path.join(folder_path, f"batch_{batch_str}.npz")
                    
                    if os.path.exists(batch_file):
                        try:
                            os.remove(batch_file)
                            removed_count += 1
                            self.logger.info("MenuSystem", f"Removed batch file: {batch_file}")
                        except Exception as e:
                            self.logger.error("MenuSystem", f"Error removing batch file {batch_file}: {e}")
            
            # Reset the batch counter to the scene batch number
            with open(batch_counter_file, "w") as f:
                f.write(str(scene_batch))
                
            # Update our batch display
            self.current_batch_var.set(str(scene_batch))
            
            # Show completion message
            self.status_label.configure(text=f"Removed {removed_count} batch files. Batch counter reset to {scene_batch}.")
            self.root.after(5000, lambda: self.status_label.configure(text=""))
            
        except Exception as e:
            self.logger.error("MenuSystem", f"Error removing batches: {e}")
            self.status_label.configure(text=f"Error: {str(e)}")
            self.root.after(3000, lambda: self.status_label.configure(text=""))

