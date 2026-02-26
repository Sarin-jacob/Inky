const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// Define paths relative to this script
const sourceHtmlPath = path.join(__dirname, 'index.html');
const sourceCssPath = path.join(__dirname, 'input.css');
const tempCssPath = path.join(__dirname, 'temp.css');
const targetDir = path.join(__dirname, '../templates');
const targetHtmlPath = path.join(targetDir, 'index.html');

console.log('Starting build process...');

try {
    // 1. Run Tailwind CLI to generate and minify the CSS
    console.log('Compiling and minifying Tailwind CSS...');
    // This assumes tailwindcss is installed in your project. 
    // If using it globally, you can remove 'npx '
    execSync(`npx @tailwindcss/cli -i "${sourceCssPath}" -o "${tempCssPath}"  --minify`, { stdio: 'inherit' });

    // 2. Read the source HTML and the newly generated CSS
    console.log('Reading files...');
    let htmlContent = fs.readFileSync(sourceHtmlPath, 'utf8');
    const cssContent = fs.readFileSync(tempCssPath, 'utf8');

    // 3. Inject the CSS into the HTML
    console.log('Injecting CSS directly into HTML...');
    const styleTag = `<style>\n${cssContent}\n</style>`;
    const tailwindCdnTag = `<script src="https://cdn.tailwindcss.com"></script>`;

    if (htmlContent.includes(tailwindCdnTag)) {
        htmlContent = htmlContent.replace(tailwindCdnTag, styleTag);
    } else if (htmlContent.includes('</head>')) {
        htmlContent = htmlContent.replace('</head>', `${styleTag}\n</head>`);
    } else {
        htmlContent += `\n${styleTag}`;
    }

    // 4. Ensure target templates directory exists
    if (!fs.existsSync(targetDir)) {
        console.log('Creating ../templates directory...');
        fs.mkdirSync(targetDir, { recursive: true });
    }

    // 5. Write the final bundled HTML to the templates folder
    console.log(`Saving bundled template to ${targetHtmlPath}...`);
    fs.writeFileSync(targetHtmlPath, htmlContent, 'utf8');

    // 6. Clean up the temporary CSS file
    fs.unlinkSync(tempCssPath);

    console.log('Build successful! Your single-file template is ready.');

} catch (error) {
    console.error('Build failed:', error.message);
    process.exit(1);
}