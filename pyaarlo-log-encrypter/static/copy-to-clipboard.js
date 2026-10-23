/*
  Borrowed from here:
  https://www.roboleary.net/2022/01/13/copy-code-to-clipboard-blog.html
  Many thanks!
 */

const copyButtonLabel = "Copy Logs";

// use a class selector if available
let blocks = document.querySelectorAll("pre");

blocks.forEach((block) => {
  // only add a button if browser supports Clipboard API
  if (navigator.clipboard) {
    let button = document.createElement("button");
    button.innerText = copyButtonLabel;
    button.addEventListener("click", copyCode);
    block.appendChild(button);
  }
});

async function copyCode(event) {
  const button = event.target;
  const pre = button.parentElement;
  let code = pre.querySelector("code");
  let text = code.innerText;
  await navigator.clipboard.writeText(text);

  button.innerText = "Logs Copied to Clipboard";

  setTimeout(()=> {
    button.innerText = copyButtonLabel;
  },1000)
}
