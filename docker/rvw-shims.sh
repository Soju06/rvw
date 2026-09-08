# Keep the rvw review-phase shims ahead of the real binaries in login shells
# (Codex runs tool commands through `bash -lc`, and Debian's /etc/profile
# resets PATH before sourcing this directory).
case ":${PATH}:" in
  *":/opt/rvw-shims:"*) ;;
  *) PATH="/opt/rvw-shims:${PATH}" ;;
esac
export PATH
