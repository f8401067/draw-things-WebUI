# DrawThings WebUI

> **Latest Version**: v1.0.3 (2026-04-12)

[🇨🇳 中文版本](README_CHINESE.md)

A DrawThings Web interface based on Python Flask and static HTML, with an attractive and user-friendly interface that is convenient for mobile operation.

Used to remotely operate DrawThings on Mac for image generation and viewing images (if using external network environment, you need to set up networking yourself).

**Note: You need to install DrawThings yourself, and enable the HTTP Server function in Advanced settings when DrawThings can generate images normally**

![Home Page](./docs/image/index.png)
![Image Browser](./docs/image/image.png)

## ✨ Features

- 🖼️ **Image Generation**: Supports custom prompts, dimensions, seed, steps and other parameters
- 🤖 **AI Prompt Refinement**: Intelligently optimize prompts (requires LLM API configuration)
- 🔍 **Server Status Check**: Real-time display of DrawThings service status and current model
- 💾 **Local Storage**: Automatically save inputs, auto-fill on next visit
- 🖼️ **Image Viewer**: Supports zoom in, zoom out, reset and save images
- ⏱️ **Time Statistics**: Records generation time for each run and calculates averages
- 🚀 **Browser Cache**: Service Worker smart caching, second visit loads instantly, supports offline browsing
- 🛡️ **NSFW Detection**: Content safety detection based on LLM, automatically identifies inappropriate content
- ⭐ **Star Rating**: 1-5 star and Bad rating functionality
- 🔎 **Smart Filtering**: Multi-dimensional filtering by date, rating, NSFW status, etc.
- 🗑️ **Batch Cleanup**: One-click deletion of all images marked as Bad
- 📝 **Logging**: Automatically logs image generation and LLM call records
- 👤 **User System**: Support registration / login / guest mode, 30-day auto-login via cookie session, server-side prompt presets

## 🚀 Quick Start

### macOS Users (Recommended)

1. **Download Application**
   - Get the `DrawThings_WebUI_MacOS.zip` file

2. **Extract and Launch**
   ```bash
   # 1. Extract zip file to any directory (e.g., Desktop, Documents, etc.)
   # 2. Ensure Launch_DrawThings_WebUI.command and DrawThings WebUI.app are in the same directory
   # 3. Double-click Launch_DrawThings_WebUI.command
   ```
   If blocked by the system, go to "System Settings" > "Privacy & Security" to allow this application to run
   
   **Notes:**
   - A Terminal window will open to display logs after launch
   - First launch requires a few seconds for initialization
   - **Do not close the Terminal window**, otherwise the application will stop running

3. **Automatic Configuration**
   - First launch will automatically create configuration files and data directories in the same level directory
   - **Important: Do not delete the data directory when updating versions**
   - Browser automatically opens http://localhost:9898

4. **Modify Configuration** (Optional)
   - Edit `config.json` directly in the same directory as the `.app` package
   - Restart the application for changes to take effect

**Advantages:**
- ✅ No Python installation required
- ✅ Ready to use out of the box
- ✅ Configuration files are easy to access and edit
- ✅ Runs independently, no dependency on system environment

---

### Other Platform Users

Please refer to [DEVELOPER.md](DEVELOPER.md) for how to start from source code.

## ⚙️ Configuration

### Configuration File Location

**Packaged Application (v1.0.3+)**:
```
your_directory/
├── DrawThings WebUI.app/
├── config.json              ← Configuration file (same level directory)
└── data/                    ← Data directory (same level directory)
    ├── generated_images/    # Generated images
    ├── thumbnails/          # Thumbnails
    ├── logs/                # Log files
    └── history.db           # History database
```

**Source Code Run**: Project root directory `config.json`

Default configuration file and data directories will be automatically created on first launch.

### How to Modify Configuration

1. **Find Configuration File**: Locate `config.json` in the same directory as the `.app` package
2. **Edit File**: Open and modify with a text editor
3. **Restart Application**: Close the Terminal window and restart the application

### Configuration Items

```json
{
  "port": 9898,
  "host": "0.0.0.0",
  "debug": false,
  "auto_open_browser": true,
  "drawthings_url": "http://127.0.0.1:7888",
  "llm_api_url": "",
  "llm_model": "",
  "llm_api_key": "",
  "thumbnail": {
    "max_size": [300, 300],
    "quality": 85,
    "format": "JPEG"
  }
}
```

| Configuration Item | Description | Default Value |
|--------|------|--------|
| `port` | Server port number | 9898 |
| `host` | Listen address (0.0.0.0=allow external access) | 0.0.0.0 |
| `debug` | Debug mode | false |
| `auto_open_browser` | Automatically open browser on startup | true |
| `drawthings_url` | DrawThings service address | http://127.0.0.1:7888 |
| `llm_api_url` | Large language model API address | - |
| `llm_model` | Large language model name | - |
| `llm_api_key` | Large language model API key | - |
| `thumbnail.max_size` | Thumbnail maximum size [width, height] | [300, 300] |
| `thumbnail.quality` | JPEG compression quality (1-100) | 85 |
| `thumbnail.format` | Output format (JPEG/PNG/WEBP) | JPEG |

### Modify Configuration

1. Find the `config.json` file
2. Modify configuration with a text editor
3. Save and restart the application

---

### Access Application

After the service starts, access in browser:
- **Home Page**: `http://localhost:9898` (or your specified port)
- **History**: `http://localhost:9898/history.html`

## 👤 User System

WebUI now supports three account modes, accessible via the top-right area of the page:

| Mode | Sign-up | Storage | Auto-login |
| --- | --- | --- | --- |
| **Registered User** | Account + password + confirm password | Server-side, password in plain text (single-user self-hosted) | 30 days via session cookie |
| **Guest** | One click, no info required | Server-side, anonymous (e.g. `游客-0007`) | 30 days, same browser is bound to the same guest |
| **Anonymous (legacy)** | Existing users prior to v1.0.4 | Auto-marked as guest; legacy `user_id` in `localStorage` is preserved | Same as guest |

- Login/registration modal pops up on first visit; switch to the "register" tab to create a new account.
- After login, the top-right area shows the username and a "logout" button.
- After logout, the page reloads to the login modal.
- Session validity is 30 days; after expiration you will be asked to log in again.
- The `secret_key` used to sign the session is stored in `config.json` (auto-generated on first launch, **do not delete it manually** unless you want all users to log in again).
- All prompt presets are now server-side and per-user; `localStorage` is no longer used for preset storage.

## 📖 Usage Instructions

### Basic Usage

1. Open browser and access `http://localhost:9898`
2. The page will automatically check DrawThings server status
3. Fill in generation parameters:
   - **Prompt**: Describe the image content you want to generate
   - **Image Size**: Select from preset sizes
   - **Seed**: Random seed (-1 means random)
   - **Negative Prompt**: Content you don't want to appear in the image
   - **Steps**: Generation steps, more steps mean better quality but slower speed
4. Click the "Generate Image" button
5. Wait for generation to complete (may take a few minutes)
6. View the generated result, you can zoom in, zoom out, and save the image
7. Click "Return to Regenerate" to generate again

---

### NSFW Auto Detection

When LLM service is configured, the system will automatically detect content safety:

1. **Auto Detection**: After image generation completes, the system will use LLM to analyze prompt content
2. **Real-time Warning**: If NSFW content is detected, a warning window will pop up to alert users
3. **Auto Tagging**: NSFW images will be tagged in the database, and can be selectively displayed in history
4. **Privacy Protection**: NSFW images are hidden by default, requiring manual toggle to display

Configuration method: Add LLM-related configuration in `config.json`:
```json
{
  "llm_api_url": "http://your-llm-server/v1/chat/completions",
  "llm_model": "your-model-name",
  "llm_api_key": "your-api-key"
}
```

---

### Thumbnail Feature

To improve image loading speed when accessing history pages from external networks, the system supports thumbnail functionality:

1. **Auto Thumbnail Generation**: After image generation completes, the system automatically generates thumbnails (approximately 300x300 pixels)
2. **Quick Preview**: History page prioritizes loading thumbnails, only loads full-size original images when clicked
3. **Bandwidth Savings**: Thumbnails are typically only 1-2% the size of original images, significantly reducing network traffic
4. **Loading Acceleration**: In external network environments, thumbnail loading is 80-100 times faster than original images

Configuration method: Customize thumbnail parameters in `config.json`:
```json
{
  "thumbnail": {
    "max_size": [300, 300],
    "quality": 85,
    "format": "JPEG"
  }
}
```

**Configuration Item Descriptions:**
- **max_size**: Thumbnail maximum size [width, height], default [300, 300]
  - Recommended range: [150, 150] ~ [600, 600]
  - Larger means clearer but also larger file size
  
- **quality**: JPEG/WEBP compression quality (1-100), default 85
  - Lower values (60-75): Smaller files, slightly lower quality
  - Medium values (80-90): Balanced choice (recommended)
  - Higher values (90-100): Better quality, larger files
  
- **format**: Output format, supports "JPEG", "PNG", "WEBP"
  - **JPEG** (recommended): Small volume, suitable for photo-type images
  - **PNG**: Lossless compression, larger volume, suitable for line drawings
  - **WEBP**: Modern format, smallest volume, slightly less compatible

**Migrate Existing Data:**
If you already have generated images but no thumbnails, you can run the migration script:
```bash
python scripts/migrate_add_thumbnails.py
```

---

### History Management

Access `http://localhost:9898/history.html` to enter the history page:

#### Browser Cache Feature
- **Auto Cache**: Images are automatically cached to browser after first visit, second visit loads instantly
- **Smart Strategy**: Prioritize loading from cache, silently update in background to keep fresh
- **Capacity Management**: Maximum 50 images cached, automatically cleans oldest
- **Offline Browsing**: Can still access cached images when network is disconnected
- **Cache Management**: Can view cache status and clear cache in filter panel

#### Rating Feature
- **Star Rating**: Click stars (★) to rate images 1-5 stars
- **Bad Marking**: Click "👎 Bad" button to mark disliked images
- **Cross-user Rating**: Can rate images from any user

#### Filter Feature
- **Date Filter**: Select specific dates to view history
- **Star Filter**: Supports multiple selection, can select multiple ratings simultaneously
- **NSFW Filter**: Can choose to show or hide NSFW content
- **User View**: Toggle between "Only Mine" or "View All Users"

#### Batch Cleanup
- **Delete Bad Images**: In Bad filter state, can one-click delete all images marked as Bad
- **Safety Mechanism**: Must be in Bad filter state before executing delete operation
- **Dual Cleanup**: Simultaneously deletes database records and original files, freeing storage space

---

## ⚠️ Precautions

### Basic Requirements
- Ensure DrawThings service is started before first run
- Image generation may take a long time (about 5 minutes)
- Generated images will be saved in `data/generated_images` directory
- User inputs are automatically saved to browser local storage

### NSFW Detection Feature
- Requires LLM service configuration to enable automatic NSFW detection
- Detection results depend on LLM model accuracy
- NSFW images are hidden by default to protect privacy and compliance
- Can manually show/hide NSFW content through toggle on history page

### Rating and Filtering
- Rating data is stored in SQLite database, regular backup recommended
- Star filter supports multiple selection, flexible combination of different ratings
- Bad image deletion operation is irreversible, please operate with caution
- Cross-user rating feature allows multi-user collaborative review

### Performance Optimization
- For large amounts of history, paginated loading is recommended
- Regular cleanup of Bad images and unnecessary records can improve query performance
- **Browser Cache**: Images are automatically cached after first visit, second visit speed increases 20-50 times
- **Thumbnail Feature**: Enabling thumbnails can greatly improve external network access speed, reducing traffic consumption by 98%

---

## ❓ Frequently Asked Questions

### NSFW Detection Not Working?
1. Check if LLM-related parameters are correctly configured in `config.json`
2. Confirm if LLM service is running normally and accessible
3. Check backend console for error logs

### Rating Feature Abnormal?
1. Check browser console for JavaScript errors
2. Verify if API requests are sent successfully

### History Loading Slow?
1. Use date or star filters to reduce data volume
2. Regularly clean up unnecessary history records
3. **Utilize Browser Cache**: Images are cached after first visit, second visit loads instantly
4. **Enable Thumbnail Feature**: Configuring thumbnails can greatly improve external network access speed

### Thumbnails Not Generated?
1. Confirm Pillow library is installed: `pip install Pillow`
2. Check if `data/thumbnails/` directory exists and has write permissions
3. Check log file `data/logs/image_generation.log`
4. For existing images, run migration script: `python scripts/migrate_add_thumbnails.py`

---

## 🤝 Contribution and Extension

Welcome to contribute code or suggestions! Main extension directions:
- More AI model integration
- Richer image editing features
- Enhanced team collaboration features
- Performance optimization and caching mechanisms

---

## 📝 Changelog

### v1.0.3 (2026-04-12)

**Major Improvements**:
- ✅ **Unified Path Management Solution**: All configuration files and data files are now saved in the same level directory as the `.app` package
- ✅ **Environment Variable Driven**: Pass application root directory through `APP_ROOT_DIR` environment variable
- ✅ **Code Simplification**: No longer distinguish between development and packaged environments, uniformly read paths from environment variables

**User Experience Enhancements**:
- Configuration files are easier to find and edit (not inside application package)
- Avoid signature issues caused by modifying application package contents
- Follows common practices for macOS applications
- More intuitive directory structure

### v1.0.2 (2026-04-12)

**Bug Fixes**:
- Fixed configuration file path error issue after PyInstaller packaging
- Fixed path loading logic for all modules

### v1.0.1 (2026-04-12)

**Bug Fixes**:
- Fixed issue where configuration file could not be modified

### v1.0.0 (Initial Release)

**Features**:
- Image generation and management
- AI prompt refinement
- NSFW detection
- Star rating system
- History and filtering
- Thumbnail support
- Browser cache optimization

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🔗 Related Links

- [Developer Guide](DEVELOPER.md) - Development environment setup, code structure, packaging deployment
- [Feature Documentation](docs/) - Detailed descriptions of various features
- [🇨🇳 中文文档](README_CHINESE.md) - Chinese version documentation
