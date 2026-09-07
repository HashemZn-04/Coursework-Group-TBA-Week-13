# Group Coursework

## Git LFS Setup Instructions (macOS)

Follow these steps to clone and work with large assets stored in this repository:

### 1. Install Git LFS via Homebrew
```bash
brew install git-lfs
```

### 2. Initialise git lfs
```bash
git lfs install
```

### 3. Track the file

```bash
git lfs track "path/to/your/file.ext"
```

### 4. Commit them

```bash
git add .gitattributes "path/to/your/file.ext"
git commit -m "Add large asset via Git LFS"
git push origin main
```