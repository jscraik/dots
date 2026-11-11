# Homebrew Bundle source for workstation tools that are intentionally not
# managed by mise/config.toml.
# One-time migration for machines with the legacy CircleCI preview cask:
#   brew uninstall --cask circleci@next
# Then apply globally (installs the stable CircleCI formula):
#   brew bundle --global

# PDF / OCR reading pipeline.
brew "poppler" # pdftotext, pdfinfo, pdftoppm, pdfimages
brew "tesseract" # OCR engine
brew "tesseract-lang" # OCR language packs
brew "ocrmypdf" # searchable PDF OCR workflow
brew "unpaper" # scanned page cleanup for OCR
brew "qpdf" # PDF repair, encryption, inspection
brew "ghostscript" # PDF/PostScript rasterization backend
brew "imagemagick" # image normalization and conversion
brew "pandoc" # document conversion

# Network and infrastructure CLIs.
brew "mise" # bootstrap runtime/tool manager
brew "mole" # SSH tunnel manager
brew "doctl" # DigitalOcean CLI
brew "infisical" # Infisical secrets CLI
brew "mosh" # roaming SSH sessions
brew "circleci" # CircleCI CLI; replaces the retired circleci@next cask
cask "openai/tools/openai" # Official OpenAI API CLI, separate from the Python SDK

# Security scanning fallbacks and optional reverse-engineering tools.
brew "gitleaks" # legacy/full-repo secret scanning compatibility
brew "ghidra" # optional reverse-engineering framework
cask "mitmproxy" # optional HTTP interception

# Hopper Disassembler is a paid/manual optional app. It is not part of the
# baseline environment gate or Brewfile-managed dependencies.
