# HK Rally Helper — Android Automation Control Panel

![Python]([https://shields.io](https://www.python.org/)
![OpenCV]([https://shields.io](https://opencv.org/)
![Platform](https://developer.android.com/tools/releases/platform-tools)



**HK Rally Helper** is a lightweight, high-performance desktop control panel engineered for computer vision automation across Android emulators, physical mobile devices, and Windows desktop apps. Powered by an OpenCV multi-scale image recognition pipeline and ADB (Android Debug Bridge), the software executes rapid, robust, and highly dynamic UI workflows.

---

## 📂 Project Architecture & Portable Distribution

When moving, deploying, or backing up your automation environment, ensure your workspace maintains the following structural integrity:

```text
HK_Project_Directory/
├── HK_App.py                 # Core Python application logic
├── HK_Run.bat                # Automated virtual environment runner & builder
├── HK_Build_Exe.bat          # Standalone PyInstaller production build script
├── platform-tools/           # [User Provided] Official Android ADB binaries folder
│   └── adb.exe
└── HK_Portable/              # Compiled Production Build (Distributable)
    ├── HK.exe                # Single standalone executable binary
    ├── hk_config.json        # User-defined workflow steps & match configurations
    ├── platform-tools/       # Combined automated distribution dependencies
    │   └── adb.exe
    └── buttons/              # Dynamically cropped OpenCV .png template matrices
```

---

## 🛠️ Prerequisites & Environmental Configuration

To run from source or build the production executable, **Python 3.12+** must be active on your Windows machine.

### Critical Step: Deploying Android Debug Bridge (`platform-tools`)
To ensure seamless, automatic hardware and emulator target identification, the system requires the localized deployment of official Android Platform Tools:

1. Download the official **SDK Platform-Tools for Windows** from Google.
2. Extract the archive and place the `platform-tools` folder directly inside your main project workspace workspace directory (alongside `HK_App.py`).
3. **Post-Build Manual Deployment:** When compiling the application into a standalone binary using the build tools, **copy** your `platform-tools` folder manually into the newly created `HK_Portable/` folder so it sits directly adjacent to `HK.exe`.

---

## 📱 Hardware & Emulator Device Linking

### Option 1: Physical Android Mobile Hardware (via `scrcpy`)
Designed for bare-metal execution on physical endpoints (e.g., Xiaomi, Redmi, Samsung):
1. In Android, navigate to **Settings > About Phone** and tap **Build Number 7 times** to unlock Developer Options.
2. Open **Developer Options** and assert the following states to `Enabled`:
   * **USB Debugging**
   * **USB Debugging (Security Settings)** — *Mandatory for Xiaomi/Redmi ecosystem to permit programmatic touch injection.*
3. Interface the handset via an authenticated USB data link.
4. *(Optional)* Launch mirroring using **`scrcpy`** to safely deactivate the hardware panel during long automation cycles:
   ```cmd
   scrcpy -d --turn-screen-off --control
   ```

### Option 2: Emulated Hardware Sandboxes (MuMu Player / BlueStacks)
Designed for local, virtualization-layer infrastructure:
1. Initialize **MuMu Player** or your preferred emulator environment.
2. Confirm ADB loopback communication is active within the emulator system preferences.
3. The control module will parse systemic installation environments (`C:\` or `D:\Program Files\Netease\MuMuPlayer\`) to auto-bridge the runtime.

---

## 🚀 Deployment Lifecycle

1. Consolidate your core environment arrays (`HK_App.py`, `platform-tools/`, and script assets) into your active path.
2. Double-click **`HK_Run.bat`** to execute the fully integrated orchestration pipeline:
   * Instantiates an isolated Python Virtual Environment (`HK_Env`).
   * Packages dependencies (`opencv-python`, `numpy`, `pyautogui`, `mss`, `pyinstaller`) seamlessly.
   * Asserts compilation rules via PyInstaller to generate `HK.exe` in the `HK_Portable/` release sector.
   * Launches the production graphical control interface instantly.

---

## 📖 Control Panel Core Operations (4-Step Workflow)

The interface isolates system management into structured modules to configure, evaluate, and fire automated routines safely.

### 1. Calibrate (Computer Vision Target Definition)
* Access the **Buttons Calibration Panel** and select **+ Add**.
* Provide an immutable alphanumeric tag for your routine node (e.g., `Join_Rally`).
* Define your target processing format:
  * **Button Image/Crop:** Drag a tight, boundary-accurate bounding box across the target canvas zone. The OpenCV multi-scale engine will evaluate frame scales dynamically at runtime to match this matrix.
  * **Fixed Screen Point Coordinate:** Intercept an absolute, static pixel matrix position over the canvas plane.

### 2. Add New Automation (Workflow Sequence Engine)
* Select **+ Step** in the main execution tree matrix.
* Assign your newly configured validation assets or inject explicit temporal anchors via a **Wait** flag.
* Tune systemic processing parameters:
  * **Timeout (s):** Use `0` to pool states indefinitely. Set specific integer bounds (e.g., `5`) to trigger immediate fallbacks if pages fail to resolve.
  * **On Timeout:** Switch structural routing between `restart cycle` or `skip step` loops depending on page severity.
  * **Delay After Tap (s):** Define explicit systemic buffer margins to compensate for remote network or render lag.

### 3. Test Mode (Dry Run Assurance Testing)
* Ensure the **Live Clicks Switch** is toggled to **Unchecked** (Disabled).
* Execute the core runtime. The engine will loop through active screen captures and run pattern assertions using localized weights. It stores a debug verification render to disk as `hk_last_detection.png` and logs operational integrity without distributing any programmatic clicks to the target window.

### 4. Live Execution Mode (Real-Time Click Injection)
* Activate the **Live Clicks Switch** toggle flag.
* Bypass the interactive safety warning modal window. The worker sequence thread will assume immediate system priority—passing real ADB touch telemetry coordinates or native desktop system click events down to the targeted app.

---

## ⏯️ Navigation & Execution Management

* **Start Engine:** Boots up the background worker thread to process your workflow sequence sequentially.
* **Pause / Resume Switch:** Instantly freezes or resumes execution mid-loop without losing your place in the workflow queue.
* **Stop:** Safely terminates the background automation sequence.
* **Terminal Log Feed:** Real-time feedback window displaying matching confidence scores (`score=1.000`), timestamps, cycle completions, and error handling logs.
